"""Cross-encoder reranker (BAAI/bge-reranker-base) via sentence-transformers.

Lazy-loaded on first use. If `sentence-transformers` isn't installed, the
reranker falls back to identity ordering and logs a one-time warning.
"""
from __future__ import annotations

import logging

from ..config import get_settings
from ..services.tracing import timed_step

logger = logging.getLogger("intelliflow.rag.reranker")

_model = None
_warned = False


def _try_load():
    global _model, _warned
    if _model is not None:
        return _model
    try:
        from sentence_transformers import CrossEncoder  # type: ignore
    except Exception as exc:
        if not _warned:
            logger.warning(
                "sentence-transformers not available (%s); reranker falling back to identity.",
                exc,
            )
            _warned = True
        return None
    name = get_settings().reranker_model
    _model = CrossEncoder(name)
    return _model


def set_reranker_model(model) -> None:
    """Test hook: inject a stub model exposing `.predict(pairs) -> list[float]`."""
    global _model
    _model = model


def reset_reranker() -> None:
    global _model
    _model = None


def rerank(query: str, candidates: list[dict], *, top_k: int = 5) -> list[dict]:
    """Rerank `candidates` (each `{id, document, ...}`) and return top-k.

    Adds a `rerank_score` field. Stable when the model is unavailable: returns
    candidates in input order, truncated to `top_k`.
    """
    if not candidates:
        return []
    model = _try_load()
    if model is None:
        out = candidates[:top_k]
        for c in out:
            c.setdefault("rerank_score", 0.0)
        return out

    pairs = [(query, c["document"]) for c in candidates]
    with timed_step("reranker", model=get_settings().reranker_model, pairs=len(pairs)):
        scores = model.predict(pairs)
    scored = []
    for c, s in zip(candidates, scores):
        c2 = dict(c)
        c2["rerank_score"] = float(s)
        scored.append(c2)
    scored.sort(key=lambda c: c["rerank_score"], reverse=True)
    return scored[:top_k]
