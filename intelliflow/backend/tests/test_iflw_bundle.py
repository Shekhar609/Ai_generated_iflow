from __future__ import annotations

import io
import zipfile

from lxml import etree

from app.schemas.flow import Citation, Component, Connection, IFlow
from app.services.iflw_bundle import (
    _fold_manifest_line,
    _manifest_mf,
    _safe_bundle_id,
    _safe_filename,
    build_iflw_bundle,
)


CITATION = Citation(source="sap_cpi_components/https_sender.md", chunk_id="0001")


def _minimal_flow(name: str = "Country Routing") -> IFlow:
    return IFlow(
        flow_name=name,
        description="t",
        components=[
            Component(id="in", type="HTTPS Sender", config={}, purpose="in", citations=[CITATION]),
            Component(id="us", type="HTTPS Receiver", config={}, purpose="us", citations=[CITATION]),
        ],
        connections=[Connection(from_="in", to="us")],
        xml_request="<r/>",
        xml_response="<r/>",
    )


def test_bundle_is_a_valid_zip_with_expected_layout():
    data = build_iflw_bundle(_minimal_flow(), flow_id="00000000-0000-0000-0000-000000000001")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = set(z.namelist())
    assert "META-INF/MANIFEST.MF" in names
    iflw_files = [n for n in names if n.endswith(".iflw")]
    assert len(iflw_files) == 1
    assert iflw_files[0].startswith("src/main/resources/scenarioflows/integrationflow/")
    assert "src/main/resources/parameters.prop" in names
    assert "src/main/resources/parameters.propdef" in names


def test_bundle_iflw_inside_zip_is_parseable_bpmn():
    data = build_iflw_bundle(_minimal_flow(), flow_id="abc-123")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        iflw_name = next(n for n in z.namelist() if n.endswith(".iflw"))
        xml = z.read(iflw_name)
    root = etree.fromstring(xml)
    assert root.tag.endswith("definitions")
    assert root.find("{http://www.omg.org/spec/BPMN/20100524/MODEL}process") is not None


def test_manifest_has_required_sap_cpi_headers():
    mf = _manifest_mf(bundle_id="my.flow.id", name="My Flow").decode("utf-8")
    # MANIFEST.MF must use CRLF line terminators per the JAR spec.
    assert "\r\n" in mf
    # Required headers for SAP CPI to recognise this as an Integration Flow bundle.
    assert "Manifest-Version: 1.0" in mf
    assert "Bundle-ManifestVersion: 2" in mf
    assert "Bundle-Name: My Flow" in mf
    assert "Bundle-SymbolicName: my.flow.id; singleton:=true" in mf
    assert "SAP-BundleType: IntegrationFlow" in mf
    assert "SAP-NodeType: IFLMAP" in mf
    assert "Import-Package:" in mf
    # Main section is terminated by a blank line (CRLF CRLF).
    assert mf.endswith("\r\n\r\n")


def test_manifest_long_lines_are_folded_to_72_bytes():
    """JAR spec: each line is at most 72 bytes incl. CRLF; continuations start with ' '."""
    mf = _manifest_mf(bundle_id="x", name="x").decode("utf-8")
    for line in mf.split("\r\n"):
        assert len(line.encode("utf-8")) <= 70, f"Line exceeds 70 bytes: {line!r}"


def test_fold_manifest_line_short_value_unchanged():
    assert _fold_manifest_line("Bundle-Name: x") == "Bundle-Name: x\r\n"


def test_fold_manifest_line_long_value_continuation_lines_start_with_space():
    folded = _fold_manifest_line("Import-Package: " + "a" * 200)
    lines = folded.split("\r\n")
    # First line plus N continuation lines, plus the empty trailing element from the split.
    assert len(lines) > 2
    for cont in lines[1:-1]:
        assert cont.startswith(" "), cont


def test_safe_filename_strips_slashes_and_spaces():
    assert _safe_filename("Country/Based Routing!") == "Country_Based_Routing"
    assert _safe_filename("") == "Integration_Flow"


def test_safe_bundle_id_keeps_dot_and_hyphen_only():
    assert _safe_bundle_id("My Flow ID 123") == "myflowid123"
    assert _safe_bundle_id("a.b-c_123") == "a.b-c123"
    assert _safe_bundle_id("") == "intelliflow.iflow"
