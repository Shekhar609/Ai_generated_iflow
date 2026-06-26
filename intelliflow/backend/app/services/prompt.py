"""Phase 2 generation prompt (PRD §9.1).

Builds the system message from retrieved KB chunks, the JSON schema for IFlow,
and the user's prompt. The retrieved chunks carry their composite chunk_id
(`{source}::{chunk_id}`) so the LLM can cite them verbatim.
"""
from __future__ import annotations

import json
from typing import Iterable

from ..schemas.flow import IFlow

SYSTEM_PROMPT_TEMPLATE = """You are an SAP CPI Solution Architect with 15 years of experience.
Convert the user's business requirement into a complete iFlow design.

GROUND your answer in the following knowledge-base chunks. Each chunk is labelled
[source :: chunk_id]. Every component you propose MUST cite at least one chunk that
justifies the choice of adapter and its configuration. Do NOT invent adapter types or
configuration patterns that are not supported by the retrieved chunks.

Allowed component types (use ONLY these — anything else will be rejected):
HTTPS Sender, SOAP Sender, OData Sender, SFTP Sender, IDoc Sender, Mail Sender,
HTTPS Receiver, SOAP Receiver, OData Receiver, SFTP Receiver, IDoc Receiver, Mail Receiver,
JMS Receiver, Content Modifier, Router, Splitter, Aggregator, Filter, Message Mapping,
XML Validator, Groovy Script, Exception Subprocess.

Return ONE JSON object matching this exact schema (no prose, no markdown):
{output_schema_json}

Citation format inside each component: a non-empty `citations` array where each entry is
`{{"source": "<source_file>", "chunk_id": "<chunk_id>"}}` taken verbatim from the chunk
header below.

RETRIEVED CHUNKS:
{retrieved_chunks}

USER REQUIREMENT:
{user_prompt}"""


def _output_schema_json() -> str:
    return json.dumps(IFlow.model_json_schema(), indent=2)


def format_chunks(chunks: Iterable) -> str:
    blocks = []
    for ch in chunks:
        source = getattr(ch, "source", None) or (ch["source"] if "source" in ch else "")
        chunk_id = getattr(ch, "chunk_id", None) or (ch["chunk_id"] if "chunk_id" in ch else "")
        text = getattr(ch, "text", None) or (ch["text"] if "text" in ch else "")
        # source_file and chunk_id are the citation keys the LLM must echo.
        # We strip any composite "::" suffix so the citation format is canonical.
        if "::" in chunk_id:
            chunk_id = chunk_id.split("::", 1)[1]
        blocks.append(f"[{source} :: {chunk_id}]\n{text}".strip())
    return "\n\n---\n\n".join(blocks) if blocks else "(no chunks retrieved)"


def build_prompt(
    user_prompt: str,
    retrieved_chunks: Iterable,
    *,
    validation_error: str | None = None,
) -> str:
    base = SYSTEM_PROMPT_TEMPLATE.format(
        output_schema_json=_output_schema_json(),
        retrieved_chunks=format_chunks(retrieved_chunks),
        user_prompt=user_prompt,
    )
    if validation_error:
        base += (
            "\n\nThe previous response failed validation with the following error. "
            "Return a corrected JSON object only (same schema):\n"
            f"{validation_error}"
        )
    return base
