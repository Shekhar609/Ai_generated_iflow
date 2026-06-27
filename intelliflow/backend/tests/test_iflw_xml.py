from __future__ import annotations

from lxml import etree

from app.schemas.flow import Citation, Component, Connection, IFlow
from app.services.iflw_xml import NS, build_iflw_xml


CITATION = Citation(source="sap_cpi_components/https_sender.md", chunk_id="0001")


def _country_routing_flow() -> IFlow:
    """The canonical fan-out flow we use across tests: HTTPS Sender → Router → 3 HTTPS Receivers."""
    return IFlow(
        flow_name="Country Routing",
        description="t",
        components=[
            Component(id="in", type="HTTPS Sender", config={"address": "/api/orders"}, purpose="entry", citations=[CITATION]),
            Component(id="map", type="Message Mapping", config={"mapping": "xml-to-json"}, purpose="map", citations=[CITATION]),
            Component(id="r", type="Router", config={}, purpose="branch", citations=[CITATION]),
            Component(id="us", type="HTTPS Receiver", config={"address": "https://us.example/api"}, purpose="us", citations=[CITATION]),
            Component(id="ind", type="HTTPS Receiver", config={"address": "https://in.example/api"}, purpose="in", citations=[CITATION]),
            Component(id="uk", type="HTTPS Receiver", config={"address": "https://uk.example/api"}, purpose="uk", citations=[CITATION]),
        ],
        connections=[
            Connection(from_="in", to="map"),
            Connection(from_="map", to="r"),
            Connection(from_="r", to="us", label="US"),
            Connection(from_="r", to="ind", label="IN"),
            Connection(from_="r", to="uk", label="UK"),
        ],
        xml_request="<r/>",
        xml_response="<r/>",
    )


def _parse(xml_bytes: bytes) -> etree._Element:
    return etree.fromstring(xml_bytes)


def test_iflw_xml_is_well_formed_and_has_expected_root():
    root = _parse(build_iflw_xml(_country_routing_flow()))
    assert root.tag == f"{{{NS['bpmn2']}}}definitions"
    assert root.findall(f"{{{NS['bpmn2']}}}collaboration")
    assert root.findall(f"{{{NS['bpmn2']}}}process")


def test_iflw_xml_has_one_participant_per_sender_and_receiver_plus_process():
    root = _parse(build_iflw_xml(_country_routing_flow()))
    collab = root.find(f"{{{NS['bpmn2']}}}collaboration")
    participants = collab.findall(f"{{{NS['bpmn2']}}}participant")
    # 1 sender + 1 IntegrationProcess + 3 receivers = 5
    assert len(participants) == 5
    types = []
    for p in participants:
        ext = p.find(f"{{{NS['bpmn2']}}}extensionElements")
        for prop in ext.findall(f"{{{NS['ifl']}}}property"):
            if prop.findtext("key") == "ifl:type":
                types.append(prop.findtext("value"))
    assert types.count("EndpointSender") == 1
    assert types.count("IntegrationProcess") == 1
    assert types.count("EndpointRecevier") == 3


def test_iflw_xml_has_message_flow_per_endpoint():
    root = _parse(build_iflw_xml(_country_routing_flow()))
    collab = root.find(f"{{{NS['bpmn2']}}}collaboration")
    mfs = collab.findall(f"{{{NS['bpmn2']}}}messageFlow")
    # 1 sender + 3 receivers
    assert len(mfs) == 4
    directions: list[str] = []
    for mf in mfs:
        ext = mf.find(f"{{{NS['bpmn2']}}}extensionElements")
        for prop in ext.findall(f"{{{NS['ifl']}}}property"):
            if prop.findtext("key") == "direction":
                directions.append(prop.findtext("value"))
    assert directions.count("Sender") == 1
    assert directions.count("Receiver") == 3


def test_iflw_xml_process_has_start_router_receivers_and_end_events():
    root = _parse(build_iflw_xml(_country_routing_flow()))
    proc = root.find(f"{{{NS['bpmn2']}}}process")
    assert len(proc.findall(f"{{{NS['bpmn2']}}}startEvent")) == 1
    assert len(proc.findall(f"{{{NS['bpmn2']}}}exclusiveGateway")) == 1
    # Receiver service tasks + mapping service task
    tasks = proc.findall(f"{{{NS['bpmn2']}}}serviceTask")
    assert len(tasks) == 1 + 3  # mapping + 3 receivers
    # 3 end events, one per receiver
    assert len(proc.findall(f"{{{NS['bpmn2']}}}endEvent")) == 3


def test_iflw_xml_router_branches_carry_their_label_as_condition():
    root = _parse(build_iflw_xml(_country_routing_flow()))
    proc = root.find(f"{{{NS['bpmn2']}}}process")
    seq_flows = proc.findall(f"{{{NS['bpmn2']}}}sequenceFlow")
    labelled = [sf for sf in seq_flows if sf.get("name") in {"US", "IN", "UK"}]
    assert len(labelled) == 3
    for sf in labelled:
        cond = sf.find(f"{{{NS['bpmn2']}}}conditionExpression")
        assert cond is not None
        assert cond.text == sf.get("name")


def test_iflw_xml_includes_bpmndi_with_shape_per_endpoint():
    root = _parse(build_iflw_xml(_country_routing_flow()))
    plane = root.find(f"{{{NS['bpmndi']}}}BPMNDiagram/{{{NS['bpmndi']}}}BPMNPlane")
    assert plane is not None
    shape_refs = {s.get("bpmnElement") for s in plane.findall(f"{{{NS['bpmndi']}}}BPMNShape")}
    # Pool + 1 sender participant + 3 receiver participants are all referenced
    assert "Participant_Process_1" in shape_refs
    assert any(r.startswith("Participant_Sender_") for r in shape_refs)
    assert sum(1 for r in shape_refs if r.startswith("Participant_Receiver_")) == 3


def test_iflw_xml_safe_for_ids_with_spaces_and_punctuation():
    """Component ids straight from the LLM often contain spaces or '/' — must be sanitized."""
    iflow = IFlow(
        flow_name="t",
        description="t",
        components=[
            Component(id="my entry", type="HTTPS Sender", config={}, purpose="in", citations=[CITATION]),
            Component(id="US/JSON out", type="HTTPS Receiver", config={}, purpose="us", citations=[CITATION]),
        ],
        connections=[Connection(from_="my entry", to="US/JSON out")],
        xml_request="<r/>",
        xml_response="<r/>",
    )
    # Parsing succeeds = ids are NCName-safe
    root = _parse(build_iflw_xml(iflow))
    assert root.tag.endswith("definitions")
