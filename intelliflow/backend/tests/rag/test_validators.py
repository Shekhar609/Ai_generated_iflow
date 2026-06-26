from __future__ import annotations

from app.rag import validators as val_mod
from app.rag.validators import (
    PHASE_1_COMPONENT_TYPES,
    build_adapter_whitelist,
    validate_iflow,
)
from app.schemas.flow import Citation, Component, Connection, IFlow

CITATION = Citation(source="sap_cpi_components/https_sender.md", chunk_id="0001")
KNOWN = {f"{CITATION.source}::{CITATION.chunk_id}"}


def _iflow(component_type: str = "HTTPS Sender", citations=None) -> IFlow:
    return IFlow(
        flow_name="Test",
        description="t",
        components=[
            Component(
                id="c1",
                type=component_type,
                config={},
                purpose="test",
                citations=citations or [CITATION],
            )
        ],
        connections=[],
        xml_request="<r/>",
        xml_response="<r/>",
    )


def test_whitelist_union_includes_phase1_enum(monkeypatch):
    monkeypatch.setattr(val_mod, "_gather_chroma_adapter_types", lambda: {"Custom Adapter"})
    wl = build_adapter_whitelist()
    assert "HTTPS Sender" in wl
    assert "Custom Adapter" in wl
    assert PHASE_1_COMPONENT_TYPES.issubset(wl)


def test_validate_passes_for_clean_iflow():
    report = validate_iflow(_iflow(), whitelist=PHASE_1_COMPONENT_TYPES, known_chunks=KNOWN)
    assert report.ok, [i.message for i in report.issues]


def test_validate_flags_hallucinated_adapter():
    report = validate_iflow(
        _iflow(component_type="Telepathy Sender"),
        whitelist=PHASE_1_COMPONENT_TYPES,
        known_chunks=KNOWN,
    )
    assert not report.ok
    assert any(i.code == "adapter_not_whitelisted" for i in report.issues)


def test_validate_flags_unknown_citation():
    report = validate_iflow(
        _iflow(),
        whitelist=PHASE_1_COMPONENT_TYPES,
        known_chunks=set(),
    )
    assert not report.ok
    assert any(i.code == "citation_not_found" for i in report.issues)


def test_validate_flags_malformed_xml():
    iflow = _iflow()
    iflow.xml_request = "<not closed>"
    report = validate_iflow(iflow, whitelist=PHASE_1_COMPONENT_TYPES, known_chunks=KNOWN)
    assert not report.ok
    assert any(i.code == "xml_not_well_formed" for i in report.issues)
