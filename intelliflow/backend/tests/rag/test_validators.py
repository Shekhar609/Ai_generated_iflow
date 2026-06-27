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
    """Minimal valid flow: Sender → Receiver. Override c1's type per test."""
    return IFlow(
        flow_name="Test",
        description="t",
        components=[
            Component(
                id="c1",
                type=component_type,
                config={},
                purpose="entry",
                citations=citations or [CITATION],
            ),
            Component(
                id="c2",
                type="HTTPS Receiver",
                config={},
                purpose="destination",
                citations=citations or [CITATION],
            ),
        ],
        connections=[Connection(from_="c1", to="c2")],
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


def test_validate_flags_sender_at_terminal():
    """Sender adapter typed for a destination (the country-routing failure mode)."""
    iflow = IFlow(
        flow_name="t",
        description="t",
        components=[
            Component(id="entry", type="HTTPS Sender", config={}, purpose="in", citations=[CITATION]),
            Component(id="out", type="HTTPS Sender", config={}, purpose="out", citations=[CITATION]),
        ],
        connections=[Connection(from_="entry", to="out")],
        xml_request="<r/>",
        xml_response="<r/>",
    )
    report = validate_iflow(iflow, whitelist=PHASE_1_COMPONENT_TYPES, known_chunks=KNOWN)
    assert not report.ok
    codes = {i.code for i in report.issues}
    assert "sender_at_terminal" in codes
    # The 'entry' Sender is fine; the 'out' Sender is the offender.
    offenders = [i.offender for i in report.issues if i.code == "sender_at_terminal"]
    assert offenders == ["HTTPS Sender"]


def test_validate_flags_receiver_at_start():
    """Receiver adapter typed for the entry point (the flipped failure mode)."""
    iflow = IFlow(
        flow_name="t",
        description="t",
        components=[
            Component(id="entry", type="HTTPS Receiver", config={}, purpose="in", citations=[CITATION]),
            Component(id="out", type="HTTPS Receiver", config={}, purpose="out", citations=[CITATION]),
        ],
        connections=[Connection(from_="entry", to="out")],
        xml_request="<r/>",
        xml_response="<r/>",
    )
    report = validate_iflow(iflow, whitelist=PHASE_1_COMPONENT_TYPES, known_chunks=KNOWN)
    assert not report.ok
    codes = {i.code for i in report.issues}
    assert "receiver_at_start" in codes


def test_validate_passes_for_fan_out_to_multiple_receivers():
    """Sender → Router → 3 Receiver destinations should validate clean."""
    iflow = IFlow(
        flow_name="t",
        description="t",
        components=[
            Component(id="in", type="HTTPS Sender", config={}, purpose="in", citations=[CITATION]),
            Component(id="r", type="Router", config={}, purpose="branch", citations=[CITATION]),
            Component(id="us", type="HTTPS Receiver", config={}, purpose="us", citations=[CITATION]),
            Component(id="ind", type="HTTPS Receiver", config={}, purpose="in", citations=[CITATION]),
            Component(id="uk", type="HTTPS Receiver", config={}, purpose="uk", citations=[CITATION]),
        ],
        connections=[
            Connection(from_="in", to="r"),
            Connection(from_="r", to="us", label="US"),
            Connection(from_="r", to="ind", label="IN"),
            Connection(from_="r", to="uk", label="UK"),
        ],
        xml_request="<r/>",
        xml_response="<r/>",
    )
    report = validate_iflow(iflow, whitelist=PHASE_1_COMPONENT_TYPES, known_chunks=KNOWN)
    assert report.ok, [i.message for i in report.issues]
