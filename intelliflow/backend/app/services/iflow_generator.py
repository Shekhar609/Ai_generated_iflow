"""Phase 2 generation pipeline: retrieve → assemble → LLM → validate.

Primary LLM is OpenAI's gpt-4-turbo. On primary failure (network / 5xx / non-JSON
response on the first attempt) the generator falls back to Anthropic's
claude-sonnet-4-6. One automatic retry on Pydantic ValidationError or validator
failure, appending the error to the prompt. Two failures → GeneratorError.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI
from anthropic import AsyncAnthropic
from pydantic import ValidationError

from ..config import get_settings
from ..rag import retriever as retriever_mod
from ..rag.retriever import RetrievedChunk
from ..rag.validators import (
    ValidatorReport,
    build_adapter_whitelist,
    validate_iflow,
)
from ..schemas.flow import IFlow
from ..services.tracing import timed_step
from .prompt import build_prompt
from .token_guard import enforce_token_cap

logger = logging.getLogger("intelliflow.generator")


class GeneratorError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        attempts: int,
        last_error: str | None = None,
        validator: ValidatorReport | None = None,
    ) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.last_error = last_error
        self.validator = validator


@dataclass
class GeneratorResult:
    iflow: IFlow
    chunks: list[RetrievedChunk]
    attempts: int
    telemetry: list[dict[str, Any]] = field(default_factory=list)


_openai_client: AsyncOpenAI | None = None
_anthropic_client: AsyncAnthropic | None = None


def _openai() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        settings = get_settings()
        _openai_client = AsyncOpenAI(
            api_key=settings.llm_api_key(),
            base_url=settings.llm_base_url,
        )
    return _openai_client


def _anthropic() -> AsyncAnthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = AsyncAnthropic(api_key=get_settings().anthropic_api_key)
    return _anthropic_client


def reset_clients() -> None:
    global _openai_client, _anthropic_client
    _openai_client = None
    _anthropic_client = None


async def _call_openai(prompt_text: str, model: str) -> tuple[str, dict[str, Any]]:
    client = _openai()
    started = time.perf_counter()
    completion = await client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt_text}],
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    raw = completion.choices[0].message.content or ""
    usage = getattr(completion, "usage", None)
    meta = {
        "provider": "openai",
        "model": model,
        "latency_ms": elapsed_ms,
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
    }
    return raw, meta


async def _call_anthropic(prompt_text: str, model: str) -> tuple[str, dict[str, Any]]:
    client = _anthropic()
    started = time.perf_counter()
    resp = await client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt_text}],
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    parts = getattr(resp, "content", []) or []
    raw = "".join(getattr(p, "text", "") for p in parts).strip()
    usage = getattr(resp, "usage", None)
    meta = {
        "provider": "anthropic",
        "model": model,
        "latency_ms": elapsed_ms,
        "prompt_tokens": getattr(usage, "input_tokens", None),
        "completion_tokens": getattr(usage, "output_tokens", None),
    }
    return raw, meta


async def _llm_call(prompt_text: str) -> tuple[str, dict[str, Any]]:
    settings = get_settings()
    try:
        raw, meta = await _call_openai(prompt_text, settings.llm_model)
        meta["fallback_used"] = False
        return raw, meta
    except Exception as exc:
        logger.warning("primary llm failed (%s), falling back to %s", exc, settings.llm_fallback_model)
        raw, meta = await _call_anthropic(prompt_text, settings.llm_fallback_model)
        meta["fallback_used"] = True
        return raw, meta


def _parse(raw: str) -> IFlow:
    data = json.loads(raw)
    return IFlow.model_validate(data)


async def generate(
    user_prompt: str,
    *,
    retriever=None,
    whitelist: set[str] | None = None,
) -> GeneratorResult:
    """Run the full pipeline. Caller can inject `retriever` (for tests)."""
    # Late binding: tests monkeypatch `retriever_mod.retrieve`, so resolve at call time.
    retriever = retriever or retriever_mod.retrieve
    telemetry: list[dict[str, Any]] = []
    with timed_step("retrieve", prompt_chars=len(user_prompt)):
        chunks, _rewrite = await retriever(user_prompt)
    telemetry.append({"step": "retrieve", "n_chunks": len(chunks)})

    # 15k-token guardrail — truncate lowest-rank chunks if the assembled prompt overflows.
    safe_chunks = enforce_token_cap(chunks, user_prompt)
    if len(safe_chunks) < len(chunks):
        telemetry.append({
            "step": "token_guard",
            "kept": len(safe_chunks),
            "dropped": len(chunks) - len(safe_chunks),
        })

    known_chunk_ids: set[str] | None = None
    if whitelist is None:
        wl = build_adapter_whitelist()
    else:
        wl = set(whitelist)

    last_error: str | None = None
    last_validator: ValidatorReport | None = None

    for attempt in range(1, 3):
        prompt_text = build_prompt(user_prompt, safe_chunks, validation_error=last_error)
        try:
            with timed_step("llm_generate", attempt=attempt):
                raw, meta = await _llm_call(prompt_text)
        except Exception as exc:
            last_error = f"LLM call failed: {exc}"
            telemetry.append({"step": "llm_generate", "attempt": attempt, "error": last_error})
            continue
        meta["attempt"] = attempt
        telemetry.append({"step": "llm_generate", **meta})

        try:
            iflow = _parse(raw)
        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = str(exc)
            telemetry.append({"step": "parse", "attempt": attempt, "error": "schema_invalid"})
            continue

        report = validate_iflow(iflow, whitelist=wl, known_chunks=known_chunk_ids)
        last_validator = report
        telemetry.append({
            "step": "validate",
            "attempt": attempt,
            "ok": report.ok,
            "issue_count": len(report.issues),
        })
        if report.ok:
            return GeneratorResult(iflow=iflow, chunks=safe_chunks, attempts=attempt, telemetry=telemetry)
        last_error = "; ".join(f"{i.field}: {i.message}" for i in report.issues[:6])

    raise GeneratorError(
        "Generator failed to produce a valid iFlow after one retry.",
        attempts=2,
        last_error=last_error,
        validator=last_validator,
    )
