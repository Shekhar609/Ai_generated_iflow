"""Render an :class:`IFlow` as a BPMN2 + SAP-CPI .iflw XML document.

The output is a *starting-point* iflw file: well-formed BPMN2 with
SAP-CPI extension elements (`ifl:property` entries, `activityType` keys,
endpoint participants with `ifl:type=EndpointSender/EndpointRecevier`)
that represents the flow's structure. It is intended to be imported into
SAP CPI Web IDE / Eclipse Adapter Development Kit and tweaked, not used
as a byte-perfect clone of CPI's own serializer output (the property keys
and shape ids differ subtly across CPI versions).

Structure produced:

  bpmn2:collaboration
    ├─ Participant: each Sender component  (ifl:type=EndpointSender)
    ├─ Participant: IntegrationProcess     (processRef=Process_1)
    ├─ Participant: each Receiver component (ifl:type=EndpointRecevier)
    ├─ MessageFlow:  Sender participant   → StartEvent inside process
    └─ MessageFlow:  Receiver ServiceTask → Receiver participant

  bpmn2:process
    ├─ StartEvent:        one per Sender component
    ├─ ServiceTask:       each orchestration step (Content Modifier,
    │                     Message Mapping, XML Validator, Splitter, etc.)
    ├─ ExclusiveGateway:  each Router
    ├─ ServiceTask:       each Receiver (activityType=ExternalCall,
    │                     subtype derived from the adapter protocol)
    ├─ EndEvent:          one after each Receiver service task
    └─ SequenceFlow:      each connection between in-process elements

  bpmndi:BPMNDiagram
    └─ Simple level-based layout (no smart routing).
"""
from __future__ import annotations

import re
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Iterable

from lxml import etree

from ..schemas.flow import Component, Connection, IFlow

# ---------- namespaces ----------------------------------------------------------------

NS = {
    "bpmn2": "http://www.omg.org/spec/BPMN/20100524/MODEL",
    "bpmndi": "http://www.omg.org/spec/BPMN/20100524/DI",
    "dc": "http://www.omg.org/spec/DD/20100524/DC",
    "di": "http://www.omg.org/spec/DD/20100524/DI",
    "ifl": "http:///com.sap.ifl.model/Ifl.xsd",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}


def _q(prefix: str, local: str) -> str:
    return f"{{{NS[prefix]}}}{local}"


# ---------- adapter type → CPI ComponentType / activityType maps ----------------------

# Protocol family per adapter type (drives ComponentType in messageFlow extensions).
_ADAPTER_COMPONENT_TYPE: dict[str, str] = {
    "HTTPS Sender": "HTTPS",
    "HTTPS Receiver": "HTTPS",
    "SOAP Sender": "SOAP",
    "SOAP Receiver": "SOAP",
    "OData Sender": "HCIOData",
    "OData Receiver": "HCIOData",
    "SFTP Sender": "SFTP",
    "SFTP Receiver": "SFTP",
    "IDoc Sender": "IDOC",
    "IDoc Receiver": "IDOC",
    "Mail Sender": "Mail",
    "Mail Receiver": "Mail",
    "JMS Receiver": "JMS",
}

# Orchestration component type → ServiceTask activityType extension.
_ORCH_ACTIVITY_TYPE: dict[str, str] = {
    "Content Modifier": "Enricher",
    "Message Mapping": "Mapping",
    "XML Validator": "XmlValidator",
    "Splitter": "Splitter",
    "Aggregator": "Gather",
    "Filter": "MessageFilter",
    "Groovy Script": "Script",
    "Exception Subprocess": "ExceptionSubprocess",
}

ROUTER_TYPE = "Router"

# Receiver service tasks get activityType=ExternalCall (CPI convention).
_RECEIVER_ACTIVITY_TYPE = "ExternalCall"


def _is_sender(t: str) -> bool:
    return t.endswith(" Sender")


def _is_receiver(t: str) -> bool:
    return t.endswith(" Receiver")


def _is_router(t: str) -> bool:
    return t == ROUTER_TYPE


# ---------- id sanitization ----------------------------------------------------------

_BPMN_ID_RE = re.compile(r"[^A-Za-z0-9_]")


def _bpmn_id(prefix: str, raw: str) -> str:
    """Return a BPMN-id-safe string. BPMN ids must match NCName rules."""
    cleaned = _BPMN_ID_RE.sub("_", raw).strip("_")
    if not cleaned or not cleaned[0].isalpha():
        cleaned = f"x_{cleaned}" if cleaned else "x"
    return f"{prefix}_{cleaned}"


# ---------- layout (simple levelized grid) -------------------------------------------

@dataclass
class _Shape:
    bpmn_element: str
    x: int
    y: int
    width: int
    height: int
    is_horizontal: bool = False  # participants are wide rectangles


@dataclass
class _Edge:
    bpmn_element: str
    waypoints: list[tuple[int, int]]


def _topological_levels(components: list[Component], connections: list[Connection]) -> dict[str, int]:
    """Assign each component a level (depth) via BFS from start nodes (in_degree=0)."""
    ids = {c.id for c in components}
    in_deg: dict[str, int] = {cid: 0 for cid in ids}
    adj: dict[str, list[str]] = defaultdict(list)
    for cn in connections:
        if cn.from_ in ids and cn.to in ids:
            adj[cn.from_].append(cn.to)
            in_deg[cn.to] += 1

    level: dict[str, int] = {}
    q: deque[str] = deque()
    for cid in ids:
        if in_deg[cid] == 0:
            level[cid] = 0
            q.append(cid)
    while q:
        cur = q.popleft()
        for nxt in adj[cur]:
            cand = level[cur] + 1
            if nxt not in level or cand > level[nxt]:
                level[nxt] = cand
                q.append(nxt)
    # Detached cycles end up unset; put them at level 0 so they at least appear.
    for cid in ids:
        level.setdefault(cid, 0)
    return level


# ---------- builder helpers ----------------------------------------------------------

def _props(parent: etree._Element, items: Iterable[tuple[str, str]]) -> etree._Element:
    """Attach an <extensionElements> block containing <ifl:property> entries."""
    ext = etree.SubElement(parent, _q("bpmn2", "extensionElements"))
    for key, value in items:
        prop = etree.SubElement(ext, _q("ifl", "property"))
        etree.SubElement(prop, "key").text = str(key)
        etree.SubElement(prop, "value").text = str(value)
    return ext


def _add_incoming_outgoing(node: etree._Element, incoming: list[str], outgoing: list[str]) -> None:
    for sf in incoming:
        etree.SubElement(node, _q("bpmn2", "incoming")).text = sf
    for sf in outgoing:
        etree.SubElement(node, _q("bpmn2", "outgoing")).text = sf


# ---------- main builder -------------------------------------------------------------

def build_iflw_xml(iflow: IFlow, *, pretty: bool = True) -> bytes:
    """Render an IFlow as a BPMN2 .iflw XML byte string."""

    components = list(iflow.components)
    connections = list(iflow.connections)
    senders = [c for c in components if _is_sender(c.type)]
    receivers = [c for c in components if _is_receiver(c.type)]
    orchestration = [c for c in components if not (_is_sender(c.type) or _is_receiver(c.type))]

    # ---- id allocation --------------------------------------------------------------

    process_id = "Process_1"
    process_participant_id = "Participant_Process_1"

    start_event_for_sender: dict[str, str] = {}
    receiver_task_for_id: dict[str, str] = {}
    end_event_for_receiver: dict[str, str] = {}
    participant_for_sender: dict[str, str] = {}
    participant_for_receiver: dict[str, str] = {}
    node_for_orch: dict[str, str] = {}

    for c in senders:
        participant_for_sender[c.id] = _bpmn_id("Participant_Sender", c.id)
        start_event_for_sender[c.id] = _bpmn_id("StartEvent", c.id)
    for c in receivers:
        participant_for_receiver[c.id] = _bpmn_id("Participant_Receiver", c.id)
        receiver_task_for_id[c.id] = _bpmn_id("ServiceTask_Receiver", c.id)
        end_event_for_receiver[c.id] = _bpmn_id("EndEvent", c.id)
    for c in orchestration:
        node_for_orch[c.id] = _bpmn_id(
            "ExclusiveGateway" if _is_router(c.type) else "Task", c.id
        )

    # A single component_id → in-process BPMN element id. For senders, this is the
    # StartEvent (they enter the process via that event). For everything else, it's
    # the task / gateway / receiver service task.
    in_process_id: dict[str, str] = {}
    in_process_id.update(start_event_for_sender)
    in_process_id.update(receiver_task_for_id)
    in_process_id.update(node_for_orch)

    # ---- sequence flow ids (one per in-process connection + one per receiver→end) ---

    seq_flow_for_conn: list[tuple[str, str, str, str | None]] = []  # (sf_id, src, tgt, label)
    seen_pairs: dict[tuple[str, str], int] = defaultdict(int)
    for cn in connections:
        src = in_process_id.get(cn.from_)
        tgt = in_process_id.get(cn.to)
        if not src or not tgt:
            continue
        key = (src, tgt)
        seen_pairs[key] += 1
        sf_id = f"SequenceFlow_{src}_{tgt}" if seen_pairs[key] == 1 else f"SequenceFlow_{src}_{tgt}_{seen_pairs[key]}"
        seq_flow_for_conn.append((sf_id, src, tgt, cn.label))

    # Receiver service task → its end event sequence flow.
    end_seq_flows: list[tuple[str, str, str]] = []  # (sf_id, src, tgt)
    for c in receivers:
        sf_id = _bpmn_id("SequenceFlow_End", c.id)
        end_seq_flows.append((sf_id, receiver_task_for_id[c.id], end_event_for_receiver[c.id]))

    # ---- incoming/outgoing per in-process node --------------------------------------

    incoming_by_node: dict[str, list[str]] = defaultdict(list)
    outgoing_by_node: dict[str, list[str]] = defaultdict(list)
    for sf_id, src, tgt, _label in seq_flow_for_conn:
        outgoing_by_node[src].append(sf_id)
        incoming_by_node[tgt].append(sf_id)
    for sf_id, src, tgt in end_seq_flows:
        outgoing_by_node[src].append(sf_id)
        incoming_by_node[tgt].append(sf_id)

    # ---- build the XML tree ---------------------------------------------------------

    nsmap = {prefix: uri for prefix, uri in NS.items() if prefix != "xsi"}
    definitions = etree.Element(
        _q("bpmn2", "definitions"),
        nsmap=nsmap,
        attrib={
            "id": "Definitions_1",
            "targetNamespace": "http://sap.com/xi/XI/SystemLocal",
        },
    )
    # xsi attribute (we keep xsi out of the default nsmap to avoid xsi:nil noise)
    definitions.set(_q("xsi", "schemaLocation"), "")

    # -- collaboration ---------------------------------------------------------------

    collab = etree.SubElement(definitions, _q("bpmn2", "collaboration"), id="Collaboration_1")

    for c in senders:
        part = etree.SubElement(
            collab,
            _q("bpmn2", "participant"),
            id=participant_for_sender[c.id],
            name=c.id,
        )
        _props(part, [("ifl:type", "EndpointSender")])

    process_part = etree.SubElement(
        collab,
        _q("bpmn2", "participant"),
        id=process_participant_id,
        name=iflow.flow_name or "Integration Process",
        processRef=process_id,
    )
    _props(process_part, [
        ("ifl:type", "IntegrationProcess"),
    ])

    for c in receivers:
        part = etree.SubElement(
            collab,
            _q("bpmn2", "participant"),
            id=participant_for_receiver[c.id],
            name=c.id,
        )
        _props(part, [("ifl:type", "EndpointRecevier")])

    # Sender messageFlows: participant → start event
    for c in senders:
        mf = etree.SubElement(
            collab,
            _q("bpmn2", "messageFlow"),
            id=_bpmn_id("MessageFlow_Sender", c.id),
            sourceRef=participant_for_sender[c.id],
            targetRef=start_event_for_sender[c.id],
        )
        protocol = _ADAPTER_COMPONENT_TYPE.get(c.type, "HTTPS")
        ifl_props = [
            ("ComponentType", protocol),
            ("direction", "Sender"),
            ("ComponentNS", "sap"),
        ]
        for k, v in (c.config or {}).items():
            ifl_props.append((str(k), str(v)))
        _props(mf, ifl_props)

    # Receiver messageFlows: receiver service task → receiver participant
    for c in receivers:
        mf = etree.SubElement(
            collab,
            _q("bpmn2", "messageFlow"),
            id=_bpmn_id("MessageFlow_Receiver", c.id),
            sourceRef=receiver_task_for_id[c.id],
            targetRef=participant_for_receiver[c.id],
        )
        protocol = _ADAPTER_COMPONENT_TYPE.get(c.type, "HTTPS")
        ifl_props = [
            ("ComponentType", protocol),
            ("direction", "Receiver"),
            ("ComponentNS", "sap"),
        ]
        for k, v in (c.config or {}).items():
            ifl_props.append((str(k), str(v)))
        _props(mf, ifl_props)

    # -- process ---------------------------------------------------------------------

    process = etree.SubElement(definitions, _q("bpmn2", "process"), id=process_id, name=iflow.flow_name or "Integration Process")
    _props(process, [
        ("transactionTimeout", "30"),
        ("namespaceMapping", ""),
    ])

    # Start events
    for c in senders:
        sid = start_event_for_sender[c.id]
        se = etree.SubElement(process, _q("bpmn2", "startEvent"), id=sid, name="Start")
        _props(se, [("componentVersion", "1.0")])
        _add_incoming_outgoing(se, incoming_by_node.get(sid, []), outgoing_by_node.get(sid, []))
        etree.SubElement(se, _q("bpmn2", "messageEventDefinition"), id=_bpmn_id("MED_Start", c.id))

    # Orchestration nodes
    for c in orchestration:
        nid = node_for_orch[c.id]
        if _is_router(c.type):
            node = etree.SubElement(process, _q("bpmn2", "exclusiveGateway"), id=nid, name=c.purpose or c.id, gatewayDirection="Diverging")
            _props(node, [("activityType", "Router"), ("componentVersion", "1.0")])
        else:
            act_type = _ORCH_ACTIVITY_TYPE.get(c.type, c.type)
            node = etree.SubElement(process, _q("bpmn2", "serviceTask"), id=nid, name=c.purpose or c.id)
            ifl_props = [("activityType", act_type), ("componentVersion", "1.0")]
            for k, v in (c.config or {}).items():
                ifl_props.append((str(k), str(v)))
            _props(node, ifl_props)
        _add_incoming_outgoing(node, incoming_by_node.get(nid, []), outgoing_by_node.get(nid, []))

    # Receiver service tasks
    for c in receivers:
        nid = receiver_task_for_id[c.id]
        st = etree.SubElement(process, _q("bpmn2", "serviceTask"), id=nid, name=c.purpose or c.id)
        ifl_props = [
            ("activityType", _RECEIVER_ACTIVITY_TYPE),
            ("componentVersion", "1.0"),
        ]
        _props(st, ifl_props)
        _add_incoming_outgoing(st, incoming_by_node.get(nid, []), outgoing_by_node.get(nid, []))

    # End events (one per receiver)
    for c in receivers:
        eid = end_event_for_receiver[c.id]
        ee = etree.SubElement(process, _q("bpmn2", "endEvent"), id=eid, name="End")
        _props(ee, [("componentVersion", "1.0")])
        _add_incoming_outgoing(ee, incoming_by_node.get(eid, []), outgoing_by_node.get(eid, []))
        etree.SubElement(ee, _q("bpmn2", "messageEventDefinition"), id=_bpmn_id("MED_End", c.id))

    # Sequence flows
    for sf_id, src, tgt, label in seq_flow_for_conn:
        attrs = {"id": sf_id, "sourceRef": src, "targetRef": tgt}
        if label:
            attrs["name"] = label
        sf = etree.SubElement(process, _q("bpmn2", "sequenceFlow"), **attrs)
        if label:
            cond = etree.SubElement(sf, _q("bpmn2", "conditionExpression"))
            cond.set(_q("xsi", "type"), "bpmn2:tFormalExpression")
            cond.text = label
    for sf_id, src, tgt in end_seq_flows:
        etree.SubElement(process, _q("bpmn2", "sequenceFlow"), id=sf_id, sourceRef=src, targetRef=tgt)

    # -- BPMNDI (simple levelized layout) --------------------------------------------

    diagram = etree.SubElement(definitions, _q("bpmndi", "BPMNDiagram"), id="BPMNDiagram_1")
    plane = etree.SubElement(diagram, _q("bpmndi", "BPMNPlane"), id="BPMNPlane_1", bpmnElement="Collaboration_1")

    LEVEL_W = 180
    NODE_H = 80
    NODE_W = 140
    BRANCH_GAP = 110
    PROCESS_X = 240
    PROCESS_Y = 80

    level = _topological_levels(components, connections)
    # Determine per-level y-ordering: assign each component a sibling index within its level.
    by_level: dict[int, list[str]] = defaultdict(list)
    for c in components:
        by_level[level[c.id]].append(c.id)
    sibling_idx: dict[str, int] = {}
    for lvl, ids_at_level in by_level.items():
        for i, cid in enumerate(ids_at_level):
            sibling_idx[cid] = i

    max_level = max(level.values()) if level else 0
    max_siblings = max(len(v) for v in by_level.values()) if by_level else 1
    process_width = max(800, (max_level + 1) * LEVEL_W + 100)
    process_height = max(300, max_siblings * (NODE_H + BRANCH_GAP) + 100)

    # Process participant pool (encompasses all in-process shapes)
    pool = etree.SubElement(plane, _q("bpmndi", "BPMNShape"), id=f"{process_participant_id}_di", bpmnElement=process_participant_id, isHorizontal="true")
    etree.SubElement(pool, _q("dc", "Bounds"), x=str(PROCESS_X), y=str(PROCESS_Y), width=str(process_width), height=str(process_height))

    # Sender participants (left of pool, stacked)
    for idx, c in enumerate(senders):
        y = PROCESS_Y + idx * (NODE_H + BRANCH_GAP)
        shape = etree.SubElement(plane, _q("bpmndi", "BPMNShape"), id=f"{participant_for_sender[c.id]}_di", bpmnElement=participant_for_sender[c.id], isHorizontal="true")
        etree.SubElement(shape, _q("dc", "Bounds"), x="40", y=str(y), width="160", height="80")

    # In-process shapes
    def _shape_for_component(c: Component, x: int, y: int) -> None:
        nid = in_process_id[c.id]
        shape = etree.SubElement(plane, _q("bpmndi", "BPMNShape"), id=f"{nid}_di", bpmnElement=nid)
        if _is_sender(c.type):
            # represented as a start event circle (smaller)
            etree.SubElement(shape, _q("dc", "Bounds"), x=str(x), y=str(y + 20), width="40", height="40")
        elif _is_router(c.type):
            etree.SubElement(shape, _q("dc", "Bounds"), x=str(x), y=str(y + 15), width="50", height="50")
        else:
            etree.SubElement(shape, _q("dc", "Bounds"), x=str(x), y=str(y), width=str(NODE_W), height=str(NODE_H))

    inside_x_origin = PROCESS_X + 40
    inside_y_origin = PROCESS_Y + 60
    for c in components:
        lvl = level[c.id]
        sib = sibling_idx[c.id]
        x = inside_x_origin + lvl * LEVEL_W
        y = inside_y_origin + sib * (NODE_H + BRANCH_GAP)
        _shape_for_component(c, x, y)

    # End events (one per receiver, placed to the right of its receiver service task)
    for c in receivers:
        lvl = level[c.id]
        sib = sibling_idx[c.id]
        x = inside_x_origin + (lvl + 1) * LEVEL_W
        y = inside_y_origin + sib * (NODE_H + BRANCH_GAP)
        eid = end_event_for_receiver[c.id]
        shape = etree.SubElement(plane, _q("bpmndi", "BPMNShape"), id=f"{eid}_di", bpmnElement=eid)
        etree.SubElement(shape, _q("dc", "Bounds"), x=str(x), y=str(y + 20), width="40", height="40")

    # Receiver participants (right of pool, stacked)
    receiver_pool_x = PROCESS_X + process_width + 40
    for idx, c in enumerate(receivers):
        y = PROCESS_Y + idx * (NODE_H + BRANCH_GAP)
        shape = etree.SubElement(plane, _q("bpmndi", "BPMNShape"), id=f"{participant_for_receiver[c.id]}_di", bpmnElement=participant_for_receiver[c.id], isHorizontal="true")
        etree.SubElement(shape, _q("dc", "Bounds"), x=str(receiver_pool_x), y=str(y), width="160", height="80")

    # Sequence flow edges (straight lines, source-center → target-center; rough)
    def _center_for(bpmn_id_str: str) -> tuple[int, int]:
        # Reverse lookup: find which component this bpmn_id belongs to.
        for cid, nid in in_process_id.items():
            if nid == bpmn_id_str:
                c = next(x for x in components if x.id == cid)
                lvl = level[c.id]
                sib = sibling_idx[c.id]
                cx = inside_x_origin + lvl * LEVEL_W + (NODE_W // 2)
                cy = inside_y_origin + sib * (NODE_H + BRANCH_GAP) + (NODE_H // 2)
                return cx, cy
        # End events
        for cid, eid in end_event_for_receiver.items():
            if eid == bpmn_id_str:
                c = next(x for x in components if x.id == cid)
                lvl = level[c.id]
                sib = sibling_idx[c.id]
                cx = inside_x_origin + (lvl + 1) * LEVEL_W + 20
                cy = inside_y_origin + sib * (NODE_H + BRANCH_GAP) + 40
                return cx, cy
        return 0, 0

    for sf_id, src, tgt, _label in seq_flow_for_conn:
        edge = etree.SubElement(plane, _q("bpmndi", "BPMNEdge"), id=f"{sf_id}_di", bpmnElement=sf_id)
        sx, sy = _center_for(src)
        tx, ty = _center_for(tgt)
        etree.SubElement(edge, _q("di", "waypoint"), x=str(sx), y=str(sy))
        etree.SubElement(edge, _q("di", "waypoint"), x=str(tx), y=str(ty))
    for sf_id, src, tgt in end_seq_flows:
        edge = etree.SubElement(plane, _q("bpmndi", "BPMNEdge"), id=f"{sf_id}_di", bpmnElement=sf_id)
        sx, sy = _center_for(src)
        tx, ty = _center_for(tgt)
        etree.SubElement(edge, _q("di", "waypoint"), x=str(sx), y=str(sy))
        etree.SubElement(edge, _q("di", "waypoint"), x=str(tx), y=str(ty))

    # Message flow edges
    for c in senders:
        mf_id = _bpmn_id("MessageFlow_Sender", c.id)
        edge = etree.SubElement(plane, _q("bpmndi", "BPMNEdge"), id=f"{mf_id}_di", bpmnElement=mf_id)
        # participant right edge → start event left
        idx = senders.index(c)
        py = PROCESS_Y + idx * (NODE_H + BRANCH_GAP) + 40
        tx, ty = _center_for(start_event_for_sender[c.id])
        etree.SubElement(edge, _q("di", "waypoint"), x="200", y=str(py))
        etree.SubElement(edge, _q("di", "waypoint"), x=str(tx), y=str(ty))
    for c in receivers:
        mf_id = _bpmn_id("MessageFlow_Receiver", c.id)
        edge = etree.SubElement(plane, _q("bpmndi", "BPMNEdge"), id=f"{mf_id}_di", bpmnElement=mf_id)
        sx, sy = _center_for(receiver_task_for_id[c.id])
        idx = receivers.index(c)
        py = PROCESS_Y + idx * (NODE_H + BRANCH_GAP) + 40
        etree.SubElement(edge, _q("di", "waypoint"), x=str(sx), y=str(sy))
        etree.SubElement(edge, _q("di", "waypoint"), x=str(receiver_pool_x), y=str(py))

    return etree.tostring(definitions, pretty_print=pretty, xml_declaration=True, encoding="UTF-8")
