from __future__ import annotations

from datetime import datetime
from typing import Any, TypedDict


class FlowDocument(TypedDict, total=False):
    _id: str
    name: str
    tags: list[str]
    prompt: str
    flow: dict[str, Any]
    created_at: datetime
    updated_at: datetime
