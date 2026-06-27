"""Anti-hallucination validators that run on every generated IFlow."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from lxml import etree
from pymongo import MongoClient

from ..config import get_settings
from ..schemas.flow import IFlow
from .chroma_client import get_kb_collection
from .ingest import KB_COLLECTION

# The Phase 1 fixed enum — union'd with KB metadata to avoid false rejections when
# the KB lacks coverage for a legitimate component.
PHASE_1_COMPONENT_TYPES: frozenset[str] = frozenset({
    "HTTPS Sender", "SOAP Sender", "OData Sender", "SFTP Sender", "IDoc Sender", "Mail Sender",
    "HTTPS Receiver", "SOAP Receiver", "OData Receiver", "SFTP Receiver", "IDoc Receiver",
    "Mail Receiver", "JMS Receiver",
    "Content Modifier", "Router", "Splitter", "Aggregator", "Filter", "Message Mapping",
    "XML Validator", "Groovy Script", "Exception Subprocess",
})


@dataclass
class ValidationIssue:
    field: str
    code: str
    message: str
    offender: str | None = None


@dataclass
class ValidatorReport:
    ok: bool
    issues: list[ValidationIssue] = field(default_factory=list)
    whitelist: list[str] = field(default_factory=list)


def _gather_chroma_adapter_types() -> set[str]:
    try:
        coll = get_kb_collection()
        res = coll.get(include=["metadatas"])
    except Exception:
        return set()
    out: set[str] = set()
    for meta in res.get("metadatas", []) or []:
        adapter = (meta or {}).get("adapter_type")
        if adapter:
            out.add(adapter)
    return out


def build_adapter_whitelist() -> set[str]:
    """Union of Phase 1 enum and ChromaDB-indexed adapter_type values."""
    return set(PHASE_1_COMPONENT_TYPES) | _gather_chroma_adapter_types()


def _check_adapters(iflow: IFlow, whitelist: Iterable[str]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    wl = set(whitelist)
    for comp in iflow.components:
        if comp.type not in wl:
            issues.append(
                ValidationIssue(
                    field=f"components[{comp.id}].type",
                    code="adapter_not_whitelisted",
                    message=f"Component type '{comp.type}' is not in the indexed KB adapter set.",
                    offender=comp.type,
                )
            )
    return issues


def _gather_known_chunk_ids(chunk_ids: Iterable[str]) -> set[str]:
    settings = get_settings()
    client = MongoClient(settings.mongodb_uri)
    try:
        coll = client[settings.mongodb_db_name][KB_COLLECTION]
        ids = list({c for c in chunk_ids if c})
        if not ids:
            return set()
        cursor = coll.find({"_id": {"$in": ids}}, {"_id": 1})
        return {doc["_id"] for doc in cursor}
    finally:
        client.close()


def _check_citations(iflow: IFlow, *, allow_known: set[str] | None = None) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    referenced: list[str] = []
    for comp in iflow.components:
        for cit in comp.citations:
            referenced.append(f"{cit.source}::{cit.chunk_id}")

    if not referenced:
        return issues

    if allow_known is None:
        known = _gather_known_chunk_ids(referenced)
    else:
        known = set(allow_known)

    for comp in iflow.components:
        if not comp.citations:
            issues.append(
                ValidationIssue(
                    field=f"components[{comp.id}].citations",
                    code="missing_citations",
                    message=f"Component '{comp.id}' has no citations.",
                )
            )
            continue
        for cit in comp.citations:
            composite = f"{cit.source}::{cit.chunk_id}"
            if composite not in known:
                issues.append(
                    ValidationIssue(
                        field=f"components[{comp.id}].citations",
                        code="citation_not_found",
                        message=f"Citation {composite} does not resolve to a known KB chunk.",
                        offender=composite,
                    )
                )
    return issues


def _is_sender(component_type: str) -> bool:
    return component_type.endswith(" Sender")


def _is_receiver(component_type: str) -> bool:
    return component_type.endswith(" Receiver")


def _check_adapter_directions(iflow: IFlow) -> list[ValidationIssue]:
    """Enforce SAP CPI adapter-direction semantics.

    Sender adapters are inbound triggers — they must be at the start of the flow
    (no incoming connections) and must have at least one outgoing connection.
    Receiver adapters are outbound destinations — they must be at the end of a
    branch (no outgoing connections) and must have at least one incoming.

    The LLM has a strong prior to use 'HTTPS Sender' for any HTTPS component
    regardless of direction, so this check is the backstop that triggers the
    retry-with-feedback path.
    """
    issues: list[ValidationIssue] = []
    in_deg: dict[str, int] = {c.id: 0 for c in iflow.components}
    out_deg: dict[str, int] = {c.id: 0 for c in iflow.components}
    for conn in iflow.connections:
        if conn.from_ in out_deg:
            out_deg[conn.from_] += 1
        if conn.to in in_deg:
            in_deg[conn.to] += 1

    for comp in iflow.components:
        if _is_sender(comp.type):
            if in_deg[comp.id] > 0:
                issues.append(ValidationIssue(
                    field=f"components[{comp.id}].type",
                    code="sender_not_at_start",
                    message=(
                        f"Component '{comp.id}' is typed '{comp.type}' (Sender = inbound trigger) "
                        f"but has {in_deg[comp.id]} incoming connection(s). Sender adapters MUST be "
                        f"at the START of the flow with no incoming edges. If this is an outbound "
                        f"call from the iFlow, change the type to the matching Receiver adapter "
                        f"(e.g. 'HTTPS Receiver' instead of 'HTTPS Sender')."
                    ),
                    offender=comp.type,
                ))
            if out_deg[comp.id] == 0:
                issues.append(ValidationIssue(
                    field=f"components[{comp.id}].type",
                    code="sender_at_terminal",
                    message=(
                        f"Component '{comp.id}' is typed '{comp.type}' (Sender = inbound trigger) "
                        f"but is a terminal node (no outgoing connections). The destinations at the "
                        f"END of a branch must be Receiver adapters, not Sender adapters. Change "
                        f"the type to the matching Receiver (e.g. 'HTTPS Receiver')."
                    ),
                    offender=comp.type,
                ))
        elif _is_receiver(comp.type):
            if out_deg[comp.id] > 0:
                issues.append(ValidationIssue(
                    field=f"components[{comp.id}].type",
                    code="receiver_not_at_end",
                    message=(
                        f"Component '{comp.id}' is typed '{comp.type}' (Receiver = outbound destination) "
                        f"but has {out_deg[comp.id]} outgoing connection(s). Receiver adapters MUST be "
                        f"at the END of a branch with no outgoing edges. If this is the inbound entry "
                        f"point of the flow, change the type to the matching Sender adapter "
                        f"(e.g. 'HTTPS Sender' instead of 'HTTPS Receiver')."
                    ),
                    offender=comp.type,
                ))
            if in_deg[comp.id] == 0:
                issues.append(ValidationIssue(
                    field=f"components[{comp.id}].type",
                    code="receiver_at_start",
                    message=(
                        f"Component '{comp.id}' is typed '{comp.type}' (Receiver = outbound destination) "
                        f"but is a start node (no incoming connections). The entry point at the START "
                        f"of the flow must be a Sender adapter, not a Receiver adapter. Change "
                        f"the type to the matching Sender (e.g. 'HTTPS Sender')."
                    ),
                    offender=comp.type,
                ))
    return issues


def _check_xml(iflow: IFlow) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for field_name in ("xml_request", "xml_response"):
        value = getattr(iflow, field_name)
        try:
            etree.fromstring(value.encode("utf-8"))
        except etree.XMLSyntaxError as exc:
            issues.append(
                ValidationIssue(
                    field=field_name,
                    code="xml_not_well_formed",
                    message=str(exc),
                )
            )
    return issues


def validate_iflow(
    iflow: IFlow,
    *,
    whitelist: Iterable[str] | None = None,
    known_chunks: set[str] | None = None,
) -> ValidatorReport:
    wl = list(whitelist) if whitelist is not None else list(build_adapter_whitelist())
    issues: list[ValidationIssue] = []
    issues.extend(_check_adapters(iflow, wl))
    issues.extend(_check_adapter_directions(iflow))
    issues.extend(_check_citations(iflow, allow_known=known_chunks))
    issues.extend(_check_xml(iflow))
    return ValidatorReport(ok=not issues, issues=issues, whitelist=wl)
