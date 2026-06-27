"""Structured-JSON tracing with contextvars-propagated request_id.

Every retrieval / LLM step emits one JSON line via the `intelliflow.trace` logger:
  {"request_id": "...", "step_name": "rewriter", "latency_ms": 42,
   "token_count": 123, "model": "..."}

A redacting filter strips any value that looks like an API key, so secrets never
leak into logs even if a developer accidentally formats one in.
"""
from __future__ import annotations

import contextvars
import json
import logging
import os
import re
import time
import uuid
from contextlib import contextmanager
from typing import Any

_request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "intelliflow_request_id", default=None
)


def new_request_id() -> str:
    rid = uuid.uuid4().hex
    _request_id_var.set(rid)
    return rid


def get_request_id() -> str | None:
    return _request_id_var.get()


def set_request_id(rid: str | None) -> None:
    _request_id_var.set(rid)


_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"gsk_[A-Za-z0-9_\-]{8,}"),
]


def redact(text: str) -> str:
    for pat in _SECRET_PATTERNS:
        text = pat.sub("[REDACTED]", text)
    return text


class _RedactingLogRecord(logging.LogRecord):
    """LogRecord subclass that redacts secrets from the formatted message.

    Applied via `logging.setLogRecordFactory` so it catches records emitted on
    any logger, regardless of which handlers/filters are attached.
    """

    def getMessage(self) -> str:  # type: ignore[override]
        return redact(super().getMessage())


logging.setLogRecordFactory(_RedactingLogRecord)

_trace_logger = logging.getLogger("intelliflow.trace")


def emit(step_name: str, **fields: Any) -> None:
    payload: dict[str, Any] = {
        "request_id": get_request_id(),
        "step_name": step_name,
    }
    payload.update({k: v for k, v in fields.items() if v is not None})
    _trace_logger.info(json.dumps(payload, default=str))


@contextmanager
def timed_step(step_name: str, **fields: Any):
    started = time.perf_counter()
    extra: dict[str, Any] = {}
    try:
        yield extra
    finally:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        emit(step_name, latency_ms=elapsed_ms, **fields, **extra)


def configure_logging(level: int | None = None) -> None:
    if level is None:
        level = getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO)
    logging.basicConfig(level=level, format="%(message)s")
