from __future__ import annotations

import xmltodict


def dict_to_xml(payload: dict, root: str = "Message") -> str:
    return xmltodict.unparse({root: payload}, pretty=True)


def default_sample_request(flow_name: str) -> str:
    return dict_to_xml(
        {
            "Header": {"FlowName": flow_name},
            "Body": {"Item": "sample"},
        },
        root="Request",
    )


def default_sample_response(flow_name: str) -> str:
    return dict_to_xml(
        {
            "Header": {"FlowName": flow_name, "Status": "OK"},
            "Body": {"Result": "processed"},
        },
        root="Response",
    )
