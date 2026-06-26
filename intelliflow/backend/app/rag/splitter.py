"""Header-aware Markdown splitter.

Walks a markdown document and emits chunks bounded by top-level (#, ##, ###) headers.
Each header section is then sub-split to fit `chunk_tokens` with `overlap_tokens`
of overlap between adjacent windows.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

_HEADER_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_logger = logging.getLogger("intelliflow.splitter")

_TOKENIZER = None
_TOKENIZER_FAILED = False


def _get_tokenizer():
    """Lazily load tiktoken; if its encoding file can't be fetched, fall back to None."""
    global _TOKENIZER, _TOKENIZER_FAILED
    if _TOKENIZER is not None or _TOKENIZER_FAILED:
        return _TOKENIZER
    try:
        import tiktoken
        _TOKENIZER = tiktoken.get_encoding("cl100k_base")
    except Exception as exc:
        _logger.warning(
            "tiktoken unavailable (%s); falling back to whitespace token counting.", exc
        )
        _TOKENIZER_FAILED = True
        _TOKENIZER = None
    return _TOKENIZER


def _count_tokens(text: str) -> int:
    tok = _get_tokenizer()
    if tok is None:
        # ~1.3 word→token ratio is a fine offline approximation.
        return max(1, int(len(text.split()) * 1.3))
    return len(tok.encode(text))


def _split_by_tokens(text: str, chunk_tokens: int, overlap_tokens: int) -> list[str]:
    if not text.strip():
        return []
    tok = _get_tokenizer()
    if tok is None:
        # Word-level windowing fallback.
        words = text.split()
        word_window = max(1, int(chunk_tokens / 1.3))
        word_overlap = max(0, int(overlap_tokens / 1.3))
        if len(words) <= word_window:
            return [text]
        step = max(1, word_window - word_overlap)
        out: list[str] = []
        for start in range(0, len(words), step):
            window = words[start : start + word_window]
            if not window:
                break
            out.append(" ".join(window))
            if start + word_window >= len(words):
                break
        return out

    ids = tok.encode(text)
    if len(ids) <= chunk_tokens:
        return [text]
    step = max(1, chunk_tokens - overlap_tokens)
    out = []
    for start in range(0, len(ids), step):
        window = ids[start : start + chunk_tokens]
        if not window:
            break
        out.append(tok.decode(window))
        if start + chunk_tokens >= len(ids):
            break
    return out


@dataclass
class MarkdownChunk:
    chunk_id: str
    text: str
    headers: list[str]


def split_markdown(
    source: str,
    *,
    chunk_tokens: int = 500,
    overlap_tokens: int = 75,
) -> list[MarkdownChunk]:
    """Split a markdown string into header-aware chunks.

    Each chunk includes its inherited header trail in `headers` so the embedder /
    LLM can see the breadcrumb. The chunk text is prefixed with the trail so vector
    similarity benefits from the context.
    """
    lines = source.splitlines()
    sections: list[tuple[list[str], list[str]]] = []
    current_headers: list[str] = []
    current_lines: list[str] = []

    def flush() -> None:
        if current_lines:
            sections.append((list(current_headers), list(current_lines)))

    for line in lines:
        m = _HEADER_RE.match(line)
        if m:
            flush()
            current_lines.clear()
            depth = len(m.group(1))
            title = m.group(2).strip()
            current_headers = current_headers[: depth - 1] + [title]
        else:
            current_lines.append(line)
    flush()

    chunks: list[MarkdownChunk] = []
    counter = 0
    for headers, body_lines in sections:
        body = "\n".join(body_lines).strip()
        if not body:
            continue
        trail = " > ".join(headers) if headers else ""
        for piece in _split_by_tokens(body, chunk_tokens, overlap_tokens):
            text = f"[{trail}]\n{piece}" if trail else piece
            chunks.append(
                MarkdownChunk(
                    chunk_id=f"{counter:04d}",
                    text=text,
                    headers=list(headers),
                )
            )
            counter += 1
    return chunks


def count_tokens(text: str) -> int:
    return _count_tokens(text)
