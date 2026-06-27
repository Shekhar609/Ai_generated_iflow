"""Local sentence-transformers embedding client with an LRU+TTL cache.

Default model is `BAAI/bge-small-en-v1.5` (384-dim, ~130 MB, CPU-friendly).
Model is lazy-loaded on first call. Vectors are L2-normalized so cosine
similarity in Chroma matches dot-product.
"""
from __future__ import annotations

import asyncio
import hashlib
from typing import Any, Sequence

from cachetools import TTLCache

from ..config import get_settings
from ..services.tracing import timed_step

_lru: TTLCache[str, list[float]] = TTLCache(maxsize=1000, ttl=3600)
_lock = asyncio.Lock()

_model: Any | None = None


def _model_factory() -> Any:
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        name = get_settings().embedding_model
        _model = SentenceTransformer(name)
    return _model


def reset_clients() -> None:
    global _model
    _model = None


def _key(text: str, model: str) -> str:
    return hashlib.sha256(f"{model}::{text}".encode("utf-8")).hexdigest()


def cache_stats() -> dict:
    return {"size": len(_lru), "maxsize": _lru.maxsize, "ttl": _lru.ttl}


def clear_cache() -> None:
    _lru.clear()


def _encode(texts: Sequence[str]) -> list[list[float]]:
    model = _model_factory()
    vecs = model.encode(list(texts), normalize_embeddings=True, convert_to_numpy=True)
    return [v.tolist() for v in vecs]


async def embed_query(text: str, *, model: str | None = None) -> list[float]:
    settings = get_settings()
    model_name = model or settings.embedding_model
    cache_key = _key(text, model_name)
    if cache_key in _lru:
        return _lru[cache_key]

    async with _lock:
        if cache_key in _lru:
            return _lru[cache_key]
        with timed_step("embed_query", model=model_name, chars=len(text)):
            vecs = await asyncio.to_thread(_encode, [text])
        vec = vecs[0]
        _lru[cache_key] = vec
        return vec


def embed_batch_sync(texts: Sequence[str], *, model: str | None = None) -> list[list[float]]:
    """Sync batch embedding used by the ingest CLI. Bypasses LRU."""
    settings = get_settings()
    model_name = model or settings.embedding_model
    with timed_step("embed_batch", model=model_name, count=len(texts)):
        return _encode(texts)
