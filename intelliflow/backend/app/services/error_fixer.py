"""AI Error Fixer (PRD §14.1).

Retrieves relevant chunks from validation/ and error_handling/, asks the LLM for a
corrected XML, then re-runs the XSD validator on the result. The response honestly
flags `still_invalid: true` rather than silently returning a broken payload.
"""
from __future__ import annotations

import difflib
import json
import logging
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI

from ..config import get_settings
from ..rag.retriever import retrieve as _retrieve
from ..services.tracing import timed_step
from .xsd_validator import XmlValidationError, validate_three_level

logger = logging.getLogger("intelliflow.fixer")

_FIXER_PROMPT = """You are an SAP CPI XML error specialist.

The user submitted an XML payload that failed validation. Use ONLY the retrieved
knowledge-base chunks below as your justification. Return ONE JSON object:

{{
  "root_cause": "<one-paragraph diagnosis>",
  "corrected_xml": "<full corrected XML payload>",
  "citations": [{{"source": "<source_file>", "chunk_id": "<chunk_id>"}}, ...]
}}

RETRIEVED CHUNKS:
{chunks}

ORIGINAL XML:
{xml}

ERROR MESSAGE:
{error_message}
"""


@dataclass
class FixResult:
    root_cause: str
    corrected_xml: str
    diff: str
    citations: list[dict[str, Any]]
    still_invalid: bool
    remaining_errors: list[XmlValidationError]


_openai: AsyncOpenAI | None = None


def _client() -> AsyncOpenAI:
    global _openai
    if _openai is None:
        _openai = AsyncOpenAI(api_key=get_settings().openai_api_key)
    return _openai


def reset_clients() -> None:
    global _openai
    _openai = None


def _format_chunks(chunks) -> str:
    blocks = []
    for c in chunks:
        source = getattr(c, "source", "")
        chunk_id = getattr(c, "chunk_id", "")
        if "::" in chunk_id:
            chunk_id = chunk_id.split("::", 1)[1]
        blocks.append(f"[{source} :: {chunk_id}]\n{getattr(c, 'text', '')}")
    return "\n\n---\n\n".join(blocks) if blocks else "(no chunks retrieved)"


async def fix_xml(
    xml: str,
    error_message: str,
    *,
    xsd_base64: str | None = None,
    retriever=None,
) -> FixResult:
    retriever = retriever or _retrieve
    query = f"XSD/XML validation error: {error_message}\nFix the payload."
    chunks, _ = await retriever(query)

    prompt = _FIXER_PROMPT.format(
        chunks=_format_chunks(chunks),
        xml=xml,
        error_message=error_message,
    )

    client = _client()
    settings = get_settings()
    with timed_step("fixer_llm", model=settings.llm_model):
        completion = await client.chat.completions.create(
            model=settings.llm_model,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}],
        )
    raw = completion.choices[0].message.content or "{}"
    data = json.loads(raw)
    corrected = data.get("corrected_xml", "") or ""
    root_cause = data.get("root_cause", "") or ""
    citations = data.get("citations") or []

    diff = "\n".join(
        difflib.unified_diff(
            xml.splitlines(),
            corrected.splitlines(),
            fromfile="original.xml",
            tofile="corrected.xml",
            lineterm="",
        )
    )

    remaining = validate_three_level(corrected, xsd_base64=xsd_base64)
    return FixResult(
        root_cause=root_cause,
        corrected_xml=corrected,
        diff=diff,
        citations=citations,
        still_invalid=bool(remaining),
        remaining_errors=remaining,
    )
