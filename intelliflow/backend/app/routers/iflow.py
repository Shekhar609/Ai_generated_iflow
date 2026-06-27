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
from ..services.iflw_bundle import build_iflw_bundle
from ..services.iflw_xml import build_iflw_xml
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


def _generator_error_http(exc: GeneratorError) -> HTTPException:
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
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=body)


async def _persist_generated(prompt: str, result) -> str:
    iflow = result.iflow
    flow_id = str(uuid.uuid4())
    now = _now()
    await flows_collection().insert_one({
        "_id": flow_id,
        "name": iflow.flow_name,
        "tags": [],
        "prompt": prompt,
        "flow": iflow.model_dump(by_alias=True),
        "retrieved_chunks": [c.to_dict() for c in result.chunks],
        "attempts": result.attempts,
        "created_at": now,
        "updated_at": now,
    })
    return flow_id


def _generated_export_response(flow_id: str, iflow: IFlow, format: str, *, prompt: str) -> Response:
    """Build a file-download Response for a freshly generated flow.

    Used only by the one-call generate-download endpoint; the regular GET export
    route loads timestamps from Mongo and keeps its own (slightly different)
    response shape.
    """
    if format == "xml":
        return Response(
            content=build_iflw_xml(iflow),
            media_type="application/xml",
            headers={
                "Content-Disposition": f'attachment; filename="iflow-{flow_id}.iflw"',
                "X-Flow-Id": flow_id,
            },
        )

    if format == "zip":
        return Response(
            content=build_iflw_bundle(iflow, flow_id=flow_id),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="iflow-{flow_id}.zip"',
                "X-Flow-Id": flow_id,
            },
        )

    now_iso = _now().isoformat()
    flow_record = {
        "flow_id": flow_id,
        "name": iflow.flow_name,
        "tags": [],
        "prompt": prompt,
        "flow": iflow.model_dump(by_alias=True),
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    if format == "pdf":
        return StreamingResponse(
            stream_pdf(flow_record),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="iflow-{flow_id}.pdf"',
                "X-Flow-Id": flow_id,
            },
        )

    return Response(
        content=json.dumps(flow_record, indent=2),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="iflow-{flow_id}.json"',
            "X-Flow-Id": flow_id,
        },
    )


@router.post("/generate", response_model=GenerateOut, status_code=status.HTTP_200_OK)
@limiter.limit(f"{get_settings().rate_limit_generations_per_minute}/minute")
async def generate(request: Request, payload: GenerateIn) -> GenerateOut:
    try:
        result = await run_generate(payload.prompt)
    except GeneratorError as exc:
        raise _generator_error_http(exc) from exc

    flow_id = await _persist_generated(payload.prompt, result)
    return GenerateOut(flow_id=flow_id, flow=result.iflow)


@router.post("/generate-download")
@limiter.limit(f"{get_settings().rate_limit_generations_per_minute}/minute")
async def generate_download(
    request: Request,
    payload: GenerateIn,
    format: Literal["json", "pdf", "xml", "zip"] = Query("zip"),
) -> Response:
    """Generate a flow and stream the export back as a downloadable file in one call.

    The persisted `flow_id` is returned in the `X-Flow-Id` response header so the
    caller can later fetch, save, tag, or re-export the same flow via the regular
    `/iflow/{flow_id}` endpoints.
    """
    try:
        result = await run_generate(payload.prompt)
    except GeneratorError as exc:
        raise _generator_error_http(exc) from exc

    flow_id = await _persist_generated(payload.prompt, result)
    return _generated_export_response(flow_id, result.iflow, format, prompt=payload.prompt)


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
    format: Literal["json", "pdf", "xml", "zip"] = Query("json"),
) -> Response:
    doc = await flows_collection().find_one({"_id": flow_id})
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Flow not found.")

    iflow_obj = IFlow.model_validate(doc["flow"])

    if format == "xml":
        xml_bytes = build_iflw_xml(iflow_obj)
        filename = f"iflow-{flow_id}.iflw"
        return Response(
            content=xml_bytes,
            media_type="application/xml",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    if format == "zip":
        zip_bytes = build_iflw_bundle(iflow_obj, flow_id=flow_id)
        filename = f"iflow-{flow_id}.zip"
        return Response(
            content=zip_bytes,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    flow_record = {
        "flow_id": doc["_id"],
        "name": doc.get("name", ""),
        "tags": doc.get("tags", []),
        "prompt": doc.get("prompt", ""),
        "flow": iflow_obj.model_dump(by_alias=True),
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
