from __future__ import annotations

from app.rag.splitter import count_tokens, split_markdown


def test_splitter_emits_header_trail():
    md = """# Top

Some intro paragraph.

## Sub A

Body of sub A. Has a few sentences worth of content.

## Sub B

Body of sub B.
"""
    chunks = split_markdown(md, chunk_tokens=500, overlap_tokens=75)
    assert len(chunks) >= 2
    headers = [c.headers for c in chunks]
    assert ["Top"] in headers
    assert ["Top", "Sub A"] in headers


def test_splitter_chunks_long_sections():
    big = "Word " * 2000  # ~2000 tokens
    md = f"# Big\n\n{big}\n"
    chunks = split_markdown(md, chunk_tokens=400, overlap_tokens=50)
    assert len(chunks) > 1
    assert all(count_tokens(c.text) <= 500 for c in chunks)


def test_splitter_handles_no_headers():
    md = "Just a body with no headers."
    chunks = split_markdown(md)
    assert len(chunks) == 1
    assert chunks[0].headers == []
