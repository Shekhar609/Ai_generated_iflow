"""15k-input-token guardrail (PRD §non-functional).

Counts tokens for the assembled prompt and, if it would exceed the cap, drops
the lowest-ranked chunks until it fits. Logs a warning trace event.
"""
from __future__ import annotations

import logging

from ..config import get_settings
from ..rag.splitter import count_tokens
from ..services.tracing import emit
from .prompt import build_prompt

logger = logging.getLogger("intelliflow.token_guard")


def enforce_token_cap(chunks, user_prompt: str) -> list:
    """Return the (possibly truncated) chunk list that fits the input-token cap.

    `chunks` is the reranked output — already in score order, so we drop from the tail.
    """
    cap = get_settings().rag_generator_input_token_cap
    kept = list(chunks)
    while kept:
        text = build_prompt(user_prompt, kept)
        if count_tokens(text) <= cap:
            return kept
        dropped = kept.pop()
        emit(
            "token_guard_drop",
            cap=cap,
            tokens=count_tokens(text),
            dropped_chunk_id=getattr(dropped, "chunk_id", None),
        )
    # All chunks dropped — return empty; the generator will still try with no context.
    emit("token_guard_exhausted", cap=cap)
    return []
