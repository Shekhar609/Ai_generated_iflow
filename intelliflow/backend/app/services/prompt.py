from __future__ import annotations

import json

from ..schemas.flow import IFlow

SYSTEM_PROMPT_TEMPLATE = """You are an SAP CPI Solution Architect with 15 years of experience.
Convert the user's business requirement into a complete iFlow design.

Use only these component types:
HTTPS Sender, SOAP Sender, OData Sender, SFTP Sender, IDoc Sender, Mail Sender,
HTTPS Receiver, SOAP Receiver, OData Receiver, SFTP Receiver, IDoc Receiver, Mail Receiver,
Content Modifier, Router, Splitter, Aggregator, Filter, Message Mapping, XML Validator,
Groovy Script, Exception Subprocess.

Return ONE JSON object matching this exact schema (no prose, no markdown):
{output_schema_json}

USER REQUIREMENT:
{user_prompt}"""


def _output_schema_json() -> str:
    return json.dumps(IFlow.model_json_schema(), indent=2)


def build_prompt(user_prompt: str, validation_error: str | None = None) -> str:
    base = SYSTEM_PROMPT_TEMPLATE.format(
        output_schema_json=_output_schema_json(),
        user_prompt=user_prompt,
    )
    if validation_error:
        base += (
            "\n\nThe previous response failed validation with the following error. "
            "Return a corrected JSON object only:\n"
            f"{validation_error}"
        )
    return base
