from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Citation(BaseModel):
    source: str = Field(..., min_length=1)
    chunk_id: str = Field(..., min_length=1)


class Component(BaseModel):
    id: str
    type: str
    config: dict[str, Any] = Field(default_factory=dict)
    purpose: str
    citations: list[Citation] = Field(..., min_length=1)


class Connection(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: str = Field(alias="from")
    to: str
    label: str | None = None


class IFlow(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    flow_name: str
    description: str
    components: list[Component]
    connections: list[Connection]
    xml_request: str
    xml_response: str
    mapping_rules: list[dict] = Field(default_factory=list)
    error_handling: dict = Field(default_factory=dict)


class GenerateIn(BaseModel):
    prompt: str = Field(..., min_length=10, max_length=4000)


class GenerateOut(BaseModel):
    flow_id: str
    flow: IFlow


class SaveIn(BaseModel):
    flow_id: str
    name: str = Field(..., min_length=1, max_length=200)
    tags: list[str] = Field(default_factory=list)


class FlowRecord(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    flow_id: str = Field(alias="_id")
    name: str
    tags: list[str] = Field(default_factory=list)
    prompt: str
    flow: IFlow
    created_at: datetime
    updated_at: datetime


class HistoryItem(BaseModel):
    flow_id: str
    name: str
    tags: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class HistoryOut(BaseModel):
    items: list[HistoryItem]
    total: int
    page: int
