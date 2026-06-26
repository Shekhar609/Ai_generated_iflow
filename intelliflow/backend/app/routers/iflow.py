from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from ..config import get_settings
from ..db import flows_collection
from ..schemas.flow import (
    GenerateIn,
    GenerateOut,
    HistoryItem,
    HistoryOut,
    IFlow,
    SaveIn,
)
from ..services.llm import LLMError, generate_iflow
from ..services.rate_limit import TokenBucket

router = APIRouter(prefix="/iflow", tags=["iflow"])

_rate_limiter = TokenBucket(capacity=get_settings().rate_limit_per_minute, interval=60.0)


def get_rate_limiter() -> TokenBucket:
    return _rate_limiter


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _record_to_history_item(doc: dict) -> HistoryItem:
    return HistoryItem(
        flow_id=doc["_id"],
        name=doc.get("name", ""),
        tags=doc.get("tags", []),
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


@router.post("/generate", response_model=GenerateOut, status_code=status.HTTP_200_OK)
async def generate(
    payload: GenerateIn,
    request: Request,
    limiter: TokenBucket = Depends(get_rate_limiter),
) -> GenerateOut:
    client_ip = request.client.host if request.client else "unknown"
    if not await limiter.allow(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded: 10 generations per minute per IP.",
        )

    try:
        iflow, _telemetry = await generate_iflow(payload.prompt)
    except LLMError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "message": str(exc),
                "attempts": exc.attempts,
                "last_error": exc.last_error,
            },
        ) from exc

    flow_id = str(uuid.uuid4())
    now = _now()
    doc = {
        "_id": flow_id,
        "name": iflow.flow_name,
        "tags": [],
        "prompt": payload.prompt,
        "flow": iflow.model_dump(by_alias=True),
        "created_at": now,
        "updated_at": now,
    }
    await flows_collection().insert_one(doc)
    return GenerateOut(flow_id=flow_id, flow=iflow)


@router.post("/save", response_model=HistoryItem)
async def save(payload: SaveIn) -> HistoryItem:
    now = _now()
    result = await flows_collection().find_one_and_update(
        {"_id": payload.flow_id},
        {"$set": {"name": payload.name, "tags": payload.tags, "updated_at": now}},
        return_document=True,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Flow not found.")
    return _record_to_history_item(result)


@router.get("/history", response_model=HistoryOut)
async def history(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
) -> HistoryOut:
    coll = flows_collection()
    total = await coll.count_documents({})
    skip = (page - 1) * limit
    cursor = coll.find({}, projection={"flow": 0, "prompt": 0}).sort("created_at", -1).skip(skip).limit(limit)
    items: list[HistoryItem] = []
    async for doc in cursor:
        items.append(_record_to_history_item(doc))
    return HistoryOut(items=items, total=total, page=page)


@router.get("/{flow_id}")
async def get_flow(flow_id: str) -> dict:
    doc = await flows_collection().find_one({"_id": flow_id})
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Flow not found.")
    return {
        "flow_id": doc["_id"],
        "name": doc.get("name", ""),
        "tags": doc.get("tags", []),
        "prompt": doc.get("prompt", ""),
        "flow": IFlow.model_validate(doc["flow"]).model_dump(by_alias=True),
        "created_at": doc["created_at"].isoformat(),
        "updated_at": doc["updated_at"].isoformat(),
    }


@router.get("/{flow_id}/export")
async def export_flow(
    flow_id: str,
    format: Literal["json", "pdf", "xml"] = Query("json"),
) -> Response:
    if format in ("pdf", "xml"):
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=f"Export format '{format}' is not implemented in Phase 1.",
        )

    doc = await flows_collection().find_one({"_id": flow_id})
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Flow not found.")

    payload = {
        "flow_id": doc["_id"],
        "name": doc.get("name", ""),
        "tags": doc.get("tags", []),
        "prompt": doc.get("prompt", ""),
        "flow": IFlow.model_validate(doc["flow"]).model_dump(by_alias=True),
        "created_at": doc["created_at"].isoformat(),
        "updated_at": doc["updated_at"].isoformat(),
    }
    body = json.dumps(payload, indent=2)
    filename = f"iflow-{flow_id}.json"
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
