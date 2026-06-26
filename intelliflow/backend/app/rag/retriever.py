"""Hybrid retrieval pipeline (PRD §5.2.3) — 7 independently testable steps.

Steps:
  1. rewrite_query              (LLM)
  2. metadata_filter            (build Chroma `where` from rewrite filters)
  3. vector_search              (top-20 over query variations, deduped)
  4. bm25_search                (top-20 over the filtered set)
  5. reciprocal_rank_fusion     (k=60)
  6. rerank                     (bge-reranker-base → top-5)
  7. assemble_context           (list[{chunk_id, source, text, score}])

The top-level `retrieve` composes them. Each helper takes its inputs explicitly;
there are no hidden globals beyond the thin client accessors.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..services.tracing import timed_step
from .bm25 import bm25_topk
from .chroma_client import get_kb_collection
from .embeddings import embed_query
from .reranker import rerank
from .rewriter import RewriteResult, rewrite_query


@dataclass
class RetrievedChunk:
    chunk_id: str
    source: str
    text: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "source": self.source,
            "text": self.text,
            "score": self.score,
            "metadata": self.metadata,
        }


# ---------- Step 2: metadata filter ---------------------------------------------------

def build_where(filters: dict[str, Any]) -> dict[str, Any] | None:
    """Convert rewriter filters to a ChromaDB `where` clause.

    Returns None when there are no filters (Chroma rejects an empty dict).
    Chroma requires `$and` when multiple top-level keys are present.
    """
    clean = {k: v for k, v in (filters or {}).items() if v}
    if not clean:
        return None
    if len(clean) == 1:
        return clean
    return {"$and": [{k: v} for k, v in clean.items()]}


# ---------- Step 3: vector search -----------------------------------------------------

async def vector_search(
    query_variations: list[str],
    *,
    where: dict[str, Any] | None,
    n_results: int = 20,
) -> list[dict]:
    """Query Chroma per variation; dedup by id keeping the best (smallest) distance."""
    if not query_variations:
        return []
    coll = get_kb_collection()
    by_id: dict[str, dict] = {}
    for q in query_variations:
        emb = await embed_query(q)
        with timed_step("chroma_query", n=n_results, has_where=bool(where)):
            res = coll.query(
                query_embeddings=[emb],
                n_results=n_results,
                where=where,
            )
        ids = (res.get("ids") or [[]])[0]
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        for _id, doc, meta, dist in zip(ids, docs, metas, dists):
            prior = by_id.get(_id)
            if prior is None or dist < prior["distance"]:
                by_id[_id] = {
                    "id": _id,
                    "document": doc,
                    "metadata": meta or {},
                    "distance": float(dist),
                }
    return sorted(by_id.values(), key=lambda c: c["distance"])


# ---------- Step 5: reciprocal rank fusion --------------------------------------------

def reciprocal_rank_fusion(
    rankings: list[list[str]],
    *,
    k: int = 60,
) -> list[tuple[str, float]]:
    """Classic RRF: score(d) = sum_i 1 / (k + rank_i(d))."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, _id in enumerate(ranking):
            scores[_id] = scores.get(_id, 0.0) + 1.0 / (k + rank + 1)
    fused = sorted(scores.items(), key=lambda t: t[1], reverse=True)
    return fused


# ---------- Step 7: context assembly --------------------------------------------------

def assemble_context(
    reranked: list[dict],
) -> list[RetrievedChunk]:
    out: list[RetrievedChunk] = []
    for c in reranked:
        meta = c.get("metadata") or {}
        out.append(
            RetrievedChunk(
                chunk_id=c["id"],
                source=meta.get("source_file", ""),
                text=c["document"],
                score=float(c.get("rerank_score", 0.0)),
                metadata=meta,
            )
        )
    return out


# ---------- Composed pipeline ---------------------------------------------------------

async def retrieve(
    user_prompt: str,
    *,
    top_k: int = 5,
    vector_n: int = 20,
    bm25_n: int = 20,
) -> tuple[list[RetrievedChunk], RewriteResult]:
    """Run the full 7-step pipeline."""
    with timed_step("retrieve_pipeline", top_k=top_k):
        rewrite = await rewrite_query(user_prompt)
        where = build_where(rewrite.filters)
        vec = await vector_search(rewrite.query_variations, where=where, n_results=vector_n)

        bm25_hits = bm25_topk(vec, query=user_prompt, k=bm25_n)
        bm25_ids = [h.chunk_id for h in bm25_hits]
        vec_ids = [c["id"] for c in vec]

        fused = reciprocal_rank_fusion([vec_ids, bm25_ids])
        by_id = {c["id"]: c for c in vec}
        fused_candidates = [by_id[_id] for _id, _ in fused if _id in by_id]
        fused_candidates = fused_candidates[: max(vector_n, bm25_n)]

        reranked = rerank(user_prompt, fused_candidates, top_k=top_k)
        chunks = assemble_context(reranked)
    return chunks, rewrite
