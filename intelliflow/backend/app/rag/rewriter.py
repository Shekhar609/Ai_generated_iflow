"""Query rewriter — turns a free-text prompt into (filters, query_variations).

Uses claude-haiku-4-5 by default for cost. Returns a structured RewriteResult.
Failure mode: if the LLM call fails or returns malformed JSON, fall back to the
identity rewrite (no filters, original query as the single variation) and emit a
warning trace event.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from anthropic import AsyncAnthropic

from ..config import get_settings
from ..services.tracing import timed_step

logger = logging.getLogger("intelliflow.rag.rewriter")

_REWRITER_SYSTEM = (
    "You rewrite user requirements about SAP Cloud Integration (CPI) iFlows so a "
    "downstream retriever can find the most relevant knowledge-base chunks. "
    "Return ONE JSON object, no prose:\n"
    "{\n"
    '  "filters": {"adapter_type"?: string, "protocol"?: string, "pattern_family"?: string, "folder"?: string},\n'
    '  "query_variations": [string, string, string]\n'
    "}\n"
    "Allowed adapter_type values: HTTPS Sender, SOAP Sender, OData Sender, SFTP Sender, IDoc Sender, Mail Sender, "
    "HTTPS Receiver, SOAP Receiver, OData Receiver, SFTP Receiver, IDoc Receiver, Mail Receiver, JMS Receiver, "
    "Content Modifier, Router, Splitter, Aggregator, Filter, Message Mapping, XML Validator, Groovy Script, Exception Subprocess. "
    "Only include filters you are confident about. The 3 variations should rephrase the same intent at different "
    "specificities (broad concept, mid-level pattern, exact adapter call)."
)


@dataclass
class RewriteResult:
    filters: dict[str, Any] = field(default_factory=dict)
    query_variations: list[str] = field(default_factory=list)
    used_fallback: bool = False


_client: AsyncAnthropic | None = None


def _client_factory() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=get_settings().anthropic_api_key)
    return _client


def reset_client() -> None:
    global _client
    _client = None


def _identity_rewrite(query: str) -> RewriteResult:
    return RewriteResult(filters={}, query_variations=[query], used_fallback=True)


def _coerce(raw: str, original_query: str) -> RewriteResult:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return _identity_rewrite(original_query)
    filters = data.get("filters") or {}
    if not isinstance(filters, dict):
        filters = {}
    variations = data.get("query_variations") or []
    if not isinstance(variations, list) or not variations:
        return _identity_rewrite(original_query)
    variations = [v for v in variations if isinstance(v, str) and v.strip()][:3]
    if not variations:
        return _identity_rewrite(original_query)
    if original_query not in variations:
        variations = [original_query, *variations][:3]
    return RewriteResult(filters=filters, query_variations=variations)


async def rewrite_query(query: str, *, model: str | None = None) -> RewriteResult:
    settings = get_settings()
    model = model or settings.llm_rewriter_model
    if not settings.anthropic_api_key:
        return _identity_rewrite(query)

    client = _client_factory()
    try:
        with timed_step("rewriter", model=model, chars=len(query)):
            resp = await client.messages.create(
                model=model,
                max_tokens=512,
                system=_REWRITER_SYSTEM,
                messages=[{"role": "user", "content": query}],
            )
    except Exception as exc:
        logger.warning("rewriter_failed: %s", exc)
        return _identity_rewrite(query)

    parts = getattr(resp, "content", []) or []
    text = "".join(getattr(p, "text", "") for p in parts).strip()
    if not text:
        return _identity_rewrite(query)
    return _coerce(text, query)
