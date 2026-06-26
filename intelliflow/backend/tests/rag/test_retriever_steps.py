from __future__ import annotations

import pytest

from app.rag.bm25 import bm25_topk, tokenize
from app.rag.retriever import (
    assemble_context,
    build_where,
    reciprocal_rank_fusion,
)


def test_build_where_empty_returns_none():
    assert build_where({}) is None
    assert build_where({"adapter_type": None}) is None


def test_build_where_single_key_passthrough():
    assert build_where({"adapter_type": "Router"}) == {"adapter_type": "Router"}


def test_build_where_multi_key_wraps_with_and():
    where = build_where({"adapter_type": "Router", "protocol": "any"})
    assert where == {"$and": [{"adapter_type": "Router"}, {"protocol": "any"}]}


def test_tokenize_lowercases_and_alphanum():
    assert tokenize("HTTPS Sender, OData!") == ["https", "sender", "odata"]


def test_bm25_returns_topk_sorted_by_score():
    candidates = [
        {"id": "a", "document": "https sender accepts inbound requests"},
        {"id": "b", "document": "odata receiver calls s/4hana cloud"},
        {"id": "c", "document": "sftp sender polls a remote directory"},
        {"id": "d", "document": "router branches by xpath"},
    ]
    hits = bm25_topk(candidates, query="https inbound", k=2)
    assert len(hits) == 2
    assert hits[0].chunk_id == "a"
    assert all(h.score >= 0 for h in hits)


def test_bm25_empty_candidates():
    assert bm25_topk([], query="x", k=5) == []


def test_rrf_blends_two_rankings():
    fused = reciprocal_rank_fusion([["a", "b", "c"], ["b", "c", "a"]], k=60)
    ids = [f[0] for f in fused]
    assert ids[0] == "b"  # appears at rank 1 + 0; best blend
    assert set(ids) == {"a", "b", "c"}


def test_assemble_context_builds_retrieved_chunks():
    reranked = [
        {"id": "src::001", "document": "text-1", "metadata": {"source_file": "src"}, "rerank_score": 0.9},
        {"id": "src::002", "document": "text-2", "metadata": {"source_file": "src"}, "rerank_score": 0.4},
    ]
    out = assemble_context(reranked)
    assert [c.chunk_id for c in out] == ["src::001", "src::002"]
    assert out[0].source == "src"
    assert out[0].score == 0.9
