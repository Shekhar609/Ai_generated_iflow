from __future__ import annotations

from pathlib import Path

from app.rag.ingest import _parse_frontmatter, walk_kb


def test_parse_frontmatter():
    src = "---\ntopic: t\nadapter_type: HTTPS Sender\n---\n\n# Body\n"
    meta, body = _parse_frontmatter(src)
    assert meta["topic"] == "t"
    assert meta["adapter_type"] == "HTTPS Sender"
    assert body.startswith("\n# Body")


def test_parse_frontmatter_missing():
    meta, body = _parse_frontmatter("# Body only\n")
    assert meta == {}
    assert "Body only" in body


def test_walk_kb_finds_seeds(tmp_path: Path):
    folder = tmp_path / "fake_kb" / "sap_cpi_components"
    folder.mkdir(parents=True)
    md = """---
topic: x
adapter_type: HTTPS Sender
protocol: HTTPS
cpi_version: "2024.05"
---

# Section

Body text long enough to make a chunk.
"""
    (folder / "thing.md").write_text(md, encoding="utf-8")
    records = walk_kb(tmp_path / "fake_kb")
    assert records
    assert records[0].source_file == "sap_cpi_components/thing.md"
    assert records[0].metadata["adapter_type"] == "HTTPS Sender"
    assert records[0].metadata["folder"] == "sap_cpi_components"
