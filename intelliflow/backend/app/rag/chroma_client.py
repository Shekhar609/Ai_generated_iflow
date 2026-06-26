"""ChromaDB persistent client + collection accessor."""
from __future__ import annotations

from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings

from ..config import get_settings

_COLLECTION_NAME = "kb_chunks"

_client: chromadb.api.client.Client | None = None


def get_chroma_client() -> chromadb.api.client.Client:
    global _client
    if _client is None:
        persist_dir: Path = get_settings().chroma_dir()
        persist_dir.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(
            path=str(persist_dir),
            settings=ChromaSettings(anonymized_telemetry=False, allow_reset=True),
        )
    return _client


def get_kb_collection():
    client = get_chroma_client()
    return client.get_or_create_collection(_COLLECTION_NAME, metadata={"hnsw:space": "cosine"})


def reset_chroma() -> None:
    """Test helper: drop the client + collection."""
    global _client
    if _client is not None:
        try:
            _client.delete_collection(_COLLECTION_NAME)
        except Exception:
            pass
    _client = None
