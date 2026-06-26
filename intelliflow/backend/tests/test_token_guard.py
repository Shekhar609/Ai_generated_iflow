from __future__ import annotations

from app.services.token_guard import enforce_token_cap


class _Chunk:
    def __init__(self, chunk_id, text):
        self.chunk_id = chunk_id
        self.text = text
        self.source = "src"


def test_token_guard_truncates_overflowing_input(monkeypatch):
    # Cap the input small enough that one big chunk overflows.
    monkeypatch.setenv("RAG_GENERATOR_INPUT_TOKEN_CAP", "200")
    from app import config
    config.get_settings.cache_clear()  # type: ignore[attr-defined]

    chunks = [
        _Chunk(f"c{i}", "lorem ipsum " * 200) for i in range(5)
    ]
    kept = enforce_token_cap(chunks, "a short prompt")
    assert len(kept) < len(chunks)


def test_token_guard_keeps_all_when_within_cap(monkeypatch):
    monkeypatch.setenv("RAG_GENERATOR_INPUT_TOKEN_CAP", "100000")
    from app import config
    config.get_settings.cache_clear()  # type: ignore[attr-defined]

    chunks = [_Chunk("c1", "short"), _Chunk("c2", "also short")]
    kept = enforce_token_cap(chunks, "p")
    assert len(kept) == 2
