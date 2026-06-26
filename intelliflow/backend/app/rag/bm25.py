"""BM25 over a candidate chunk set.

Tokenization is intentionally simple: lowercase, alphanumeric word boundaries.
The corpus is the set of chunks returned by the metadata pre-filter, so we
re-index per query — acceptable for ChromaDB-scale corpora (~ thousands).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from rank_bm25 import BM25Okapi


_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


@dataclass
class BM25Result:
    chunk_id: str
    score: float


def bm25_topk(
    candidates: list[dict],
    *,
    query: str,
    k: int = 20,
) -> list[BM25Result]:
    """`candidates` must each carry `id` and `document` (the chunk text)."""
    if not candidates:
        return []
    docs = [tokenize(c["document"]) for c in candidates]
    if not any(docs):
        return []
    bm25 = BM25Okapi(docs)
    scores = bm25.get_scores(tokenize(query))
    paired = list(zip(candidates, scores))
    paired.sort(key=lambda t: t[1], reverse=True)
    out: list[BM25Result] = []
    for c, s in paired[:k]:
        out.append(BM25Result(chunk_id=c["id"], score=float(s)))
    return out
