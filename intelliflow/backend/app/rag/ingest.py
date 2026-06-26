"""Knowledge-base ingest pipeline.

Walks `knowledge_base/`, parses each .md file, splits with the header-aware splitter,
embeds with text-embedding-3-small, and upserts into both ChromaDB and Mongo
`kb_chunks`. Idempotent by (source_file, chunk_id).

CLI:
    python -m app.rag.ingest
    python -m app.rag.ingest --kb path/to/knowledge_base
    python -m app.rag.ingest --reset   # drop + reindex
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pymongo import ASCENDING, MongoClient, UpdateOne

from ..config import get_settings
from ..services.tracing import configure_logging, emit
from .chroma_client import get_kb_collection, reset_chroma
from .embeddings import embed_batch_sync
from .splitter import MarkdownChunk, split_markdown

logger = logging.getLogger("intelliflow.ingest")

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)

KB_COLLECTION = "kb_chunks"


@dataclass
class IngestRecord:
    source_file: str
    chunk_id: str
    text: str
    metadata: dict[str, Any]

    @property
    def composite_id(self) -> str:
        return f"{self.source_file}::{self.chunk_id}"


def _parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    m = _FRONTMATTER_RE.match(content)
    if not m:
        return {}, content
    meta = yaml.safe_load(m.group(1)) or {}
    if not isinstance(meta, dict):
        meta = {}
    body = content[m.end():]
    return meta, body


def _file_metadata(path: Path, kb_root: Path) -> dict[str, Any]:
    rel = path.relative_to(kb_root).as_posix()
    return {
        "source_file": rel,
        "folder": rel.split("/", 1)[0],
    }


def walk_kb(kb_root: Path) -> list[IngestRecord]:
    """Walk the KB, split each file, and return per-chunk ingest records."""
    if not kb_root.exists():
        raise FileNotFoundError(f"KB root not found: {kb_root}")

    records: list[IngestRecord] = []
    for md_path in sorted(kb_root.rglob("*.md")):
        text = md_path.read_text(encoding="utf-8")
        frontmatter, body = _parse_frontmatter(text)
        file_meta = _file_metadata(md_path, kb_root)
        chunks: list[MarkdownChunk] = split_markdown(body)
        for ch in chunks:
            meta = {
                "topic": frontmatter.get("topic"),
                "adapter_type": frontmatter.get("adapter_type"),
                "protocol": frontmatter.get("protocol"),
                "pattern_family": frontmatter.get("pattern_family"),
                "cpi_version": str(frontmatter.get("cpi_version", "")),
                "source_file": file_meta["source_file"],
                "folder": file_meta["folder"],
                "chunk_id": ch.chunk_id,
                "headers": " > ".join(ch.headers),
            }
            meta = {k: v for k, v in meta.items() if v not in (None, "")}
            records.append(
                IngestRecord(
                    source_file=file_meta["source_file"],
                    chunk_id=ch.chunk_id,
                    text=ch.text,
                    metadata=meta,
                )
            )
    return records


def _ensure_mongo_indexes(coll) -> None:
    coll.create_index(
        [("source_file", ASCENDING), ("chunk_id", ASCENDING)],
        unique=True,
        name="source_chunk_unique",
    )
    coll.create_index([("adapter_type", ASCENDING)], name="adapter_type_idx")
    coll.create_index([("folder", ASCENDING)], name="folder_idx")


def _upsert_mongo(records: list[IngestRecord]) -> int:
    settings = get_settings()
    client: MongoClient = MongoClient(settings.mongodb_uri)
    db = client[settings.mongodb_db_name]
    coll = db[KB_COLLECTION]
    _ensure_mongo_indexes(coll)
    ops = []
    for r in records:
        ops.append(
            UpdateOne(
                {"source_file": r.source_file, "chunk_id": r.chunk_id},
                {
                    "$set": {
                        "_id": r.composite_id,
                        "source_file": r.source_file,
                        "chunk_id": r.chunk_id,
                        "text": r.text,
                        **r.metadata,
                    }
                },
                upsert=True,
            )
        )
    if not ops:
        return 0
    result = coll.bulk_write(ops, ordered=False)
    client.close()
    return (result.upserted_count or 0) + (result.modified_count or 0)


def _upsert_chroma(records: list[IngestRecord], embeddings: list[list[float]]) -> int:
    coll = get_kb_collection()
    coll.upsert(
        ids=[r.composite_id for r in records],
        embeddings=embeddings,
        documents=[r.text for r in records],
        metadatas=[r.metadata for r in records],
    )
    return len(records)


def ingest(kb_root: Path | None = None, *, reset: bool = False, batch: int = 64) -> dict[str, int]:
    """Run a full ingest. Returns counts for {records, mongo_upserts, chroma_upserts}."""
    settings = get_settings()
    kb_root = kb_root or settings.kb_dir()
    if reset:
        reset_chroma()

    records = walk_kb(kb_root)
    if not records:
        emit("ingest_empty", kb_root=str(kb_root))
        return {"records": 0, "mongo_upserts": 0, "chroma_upserts": 0}

    embeddings: list[list[float]] = []
    for i in range(0, len(records), batch):
        chunk = records[i : i + batch]
        vecs = embed_batch_sync([r.text for r in chunk])
        embeddings.extend(vecs)

    mongo_n = _upsert_mongo(records)
    chroma_n = _upsert_chroma(records, embeddings)
    emit(
        "ingest_done",
        kb_root=str(kb_root),
        records=len(records),
        mongo_upserts=mongo_n,
        chroma_upserts=chroma_n,
    )
    return {"records": len(records), "mongo_upserts": mongo_n, "chroma_upserts": chroma_n}


def _cli() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="Ingest the IntelliFlow knowledge base.")
    parser.add_argument("--kb", type=Path, default=None, help="Path to knowledge_base/")
    parser.add_argument("--reset", action="store_true", help="Drop Chroma collection before reindex.")
    args = parser.parse_args()
    counts = ingest(args.kb, reset=args.reset)
    print(counts)


if __name__ == "__main__":
    _cli()
