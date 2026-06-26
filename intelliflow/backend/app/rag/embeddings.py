"""OpenAI embedding client with an LRU+TTL cache."""
from __future__ import annotations

import asyncio
import hashlib
from typing import Sequence

from cachetools import TTLCache
from openai import AsyncOpenAI, OpenAI

from ..config import get_settings
from ..services.tracing import timed_step

_lru: TTLCache[str, list[float]] = TTLCache(maxsize=1000, ttl=3600)
_lock = asyncio.Lock()

_async_client: AsyncOpenAI | None = None
_sync_client: OpenAI | None = None


def _async_client_factory() -> AsyncOpenAI:
    global _async_client
    if _async_client is None:
        _async_client = AsyncOpenAI(api_key=get_settings().openai_api_key)
    return _async_client


def _sync_client_factory() -> OpenAI:
    global _sync_client
    if _sync_client is None:
        _sync_client = OpenAI(api_key=get_settings().openai_api_key)
    return _sync_client


def reset_clients() -> None:
    global _async_client, _sync_client
    _async_client = None
    _sync_client = None


def _key(text: str, model: str) -> str:
    h = hashlib.sha256(f"{model}::{text}".encode("utf-8")).hexdigest()
    return h


def cache_stats() -> dict:
    return {"size": len(_lru), "maxsize": _lru.maxsize, "ttl": _lru.ttl}


def clear_cache() -> None:
    _lru.clear()


async def embed_query(text: str, *, model: str | None = None) -> list[float]:
    settings = get_settings()
    model = model or settings.embedding_model
    cache_key = _key(text, model)
    if cache_key in _lru:
        return _lru[cache_key]

    async with _lock:
        if cache_key in _lru:
            return _lru[cache_key]
        client = _async_client_factory()
        with timed_step("embed_query", model=model, chars=len(text)):
            resp = await client.embeddings.create(model=model, input=text)
        vec = resp.data[0].embedding
        _lru[cache_key] = vec
        return vec


def embed_batch_sync(texts: Sequence[str], *, model: str | None = None) -> list[list[float]]:
    """Sync batch embedding used by the ingest CLI. Bypasses LRU."""
    settings = get_settings()
    model = model or settings.embedding_model
    client = _sync_client_factory()
    with timed_step("embed_batch", model=model, count=len(texts)):
        resp = client.embeddings.create(model=model, input=list(texts))
    return [d.embedding for d in resp.data]
