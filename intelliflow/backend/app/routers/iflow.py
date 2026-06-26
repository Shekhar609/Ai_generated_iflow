from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse

from ..db import flows_collection
from ..schemas.flow import (
    GenerateIn,
    GenerateOut,
    HistoryItem,
    HistoryOut,
    IFlow,
    SaveIn,
)
from ..schemas.validation import (
    FixXmlIn,
    FixXmlOut,
    ValidateXmlIn,
    ValidateXmlOut,
    ValidationError as ValidationErrorOut,
)
from ..services.error_fixer import fix_xml as run_fixer
from ..services.iflow_generator import GeneratorError, generate as run_generate
from ..services.limiter import limiter
from ..services.pdf import stream_pdf
from ..services.xsd_validator import validate_three_level
from ..config import get_settings

router = APIRouter(prefix="/iflow", tags=["iflow"])


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
@limiter.limit(f"{get_settings().rate_limit_generations_per_minute}/minute")
async def generate(request: Request, payload: GenerateIn) -> GenerateOut:
    try:
        result = await run_generate(payload.prompt)
    except GeneratorError as exc:
        report = exc.validator
        body = {
            "message": str(exc),
            "attempts": exc.attempts,
            "last_error": exc.last_error,
            "issues": [
                {"field": i.field, "code": i.code, "message": i.message, "offender": i.offender}
                for i in (report.issues if report else [])
            ],
        }
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=body) from exc

    iflow = result.iflow
    flow_id = str(uuid.uuid4())
    now = _now()
    doc = {
        "_id": flow_id,
        "name": iflow.flow_name,
        "tags": [],
        "prompt": payload.prompt,
        "flow": iflow.model_dump(by_alias=True),
        "retrieved_chunks": [c.to_dict() for c in result.chunks],
        "attempts": result.attempts,
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
    cursor = coll.find({}, projection={"flow": 0, "prompt": 0, "retrieved_chunks": 0}).sort(
        "created_at", -1
    ).skip(skip).limit(limit)
    items: list[HistoryItem] = []
    async for doc in cursor:
        items.append(_record_to_history_item(doc))
    return HistoryOut(items=items, total=total, page=page)


@router.post("/validate-xml", response_model=ValidateXmlOut)
async def validate_xml(payload: ValidateXmlIn) -> ValidateXmlOut:
    errors = validate_three_level(
        payload.xml,
        xsd_base64=payload.xsd_base64,
        required_fields=payload.required_fields,
    )
    return ValidateXmlOut(
        valid=not errors,
        errors=[
            ValidationErrorOut(level=e.level, message=e.message, xpath=e.xpath, line=e.line)
            for e in errors
        ],
    )


@router.post("/fix-xml", response_model=FixXmlOut)
async def fix_xml_route(payload: FixXmlIn) -> FixXmlOut:
    result = await run_fixer(payload.xml, payload.error_message, xsd_base64=payload.xsd_base64)
    return FixXmlOut(
        root_cause=result.root_cause,
        corrected_xml=result.corrected_xml,
        diff=result.diff,
        citations=result.citations,
        still_invalid=result.still_invalid,
        remaining_errors=[
            ValidationErrorOut(level=e.level, message=e.message, xpath=e.xpath, line=e.line)
            for e in result.remaining_errors
        ],
    )


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
        "retrieved_chunks": doc.get("retrieved_chunks", []),
        "created_at": doc["created_at"].isoformat(),
        "updated_at": doc["updated_at"].isoformat(),
    }


@router.get("/{flow_id}/export")
async def export_flow(
    flow_id: str,
    format: Literal["json", "pdf", "xml"] = Query("json"),
) -> Response:
    if format == "xml":
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="XML export is not implemented in Phase 2.",
        )

    doc = await flows_collection().find_one({"_id": flow_id})
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Flow not found.")

    flow_record = {
        "flow_id": doc["_id"],
        "name": doc.get("name", ""),
        "tags": doc.get("tags", []),
        "prompt": doc.get("prompt", ""),
        "flow": IFlow.model_validate(doc["flow"]).model_dump(by_alias=True),
        "created_at": doc["created_at"].isoformat(),
        "updated_at": doc["updated_at"].isoformat(),
    }

    if format == "pdf":
        filename = f"iflow-{flow_id}.pdf"
        return StreamingResponse(
            stream_pdf(flow_record),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    body = json.dumps(flow_record, indent=2)
    filename = f"iflow-{flow_id}.json"
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
