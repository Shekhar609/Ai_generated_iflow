from __future__ import annotations

import json
import logging
import time
from typing import Any

from openai import AsyncOpenAI
from pydantic import ValidationError

from ..config import get_settings
from ..schemas.flow import IFlow
from .prompt import build_prompt
from .xml_validator import well_formed

logger = logging.getLogger("intelliflow.llm")


class LLMError(RuntimeError):
    def __init__(self, message: str, *, attempts: int, last_error: str | None = None) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.last_error = last_error


_client: AsyncOpenAI | None = None


def get_openai_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        settings = get_settings()
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


def reset_openai_client() -> None:
    global _client
    _client = None


async def _one_call(prompt_text: str, model: str) -> tuple[str, dict[str, Any]]:
    client = get_openai_client()
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
        "latency_ms": elapsed_ms,
        "model": model,
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
    }
    return raw, meta


def _parse_and_validate(raw: str) -> IFlow:
    data = json.loads(raw)
    return IFlow.model_validate(data)


async def generate_iflow(user_prompt: str) -> tuple[IFlow, list[dict[str, Any]]]:
    """Call the LLM and return a validated IFlow plus per-attempt telemetry.

    Retries once if the model returns invalid JSON/schema or non-well-formed XML.
    Raises LLMError after the second failure.
    """
    settings = get_settings()
    model = settings.llm_model
    call_log: list[dict[str, Any]] = []
    last_error: str | None = None

    for attempt in range(1, 3):
        prompt_text = build_prompt(user_prompt, validation_error=last_error)
        try:
            raw, meta = await _one_call(prompt_text, model)
        except Exception as exc:
            last_error = f"OpenAI call failed: {exc}"
            call_log.append({"attempt": attempt, "error": last_error})
            logger.error(json.dumps({"event": "llm_call_failed", "attempt": attempt, "error": last_error}))
            continue

        meta["attempt"] = attempt
        meta["prompt_chars"] = len(prompt_text)
        logger.info(json.dumps({"event": "llm_call", **{k: v for k, v in meta.items() if v is not None}}))

        try:
            iflow = _parse_and_validate(raw)
        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = str(exc)
            meta["error"] = "schema_invalid"
            call_log.append(meta)
            continue

        if not (well_formed(iflow.xml_request) and well_formed(iflow.xml_response)):
            last_error = "xml_request or xml_response is not well-formed XML."
            meta["error"] = "xml_not_well_formed"
            call_log.append(meta)
            continue

        meta["status"] = "ok"
        call_log.append(meta)
        return iflow, call_log

    raise LLMError(
        "LLM failed to produce a valid iFlow after retry.",
        attempts=2,
        last_error=last_error,
    )
