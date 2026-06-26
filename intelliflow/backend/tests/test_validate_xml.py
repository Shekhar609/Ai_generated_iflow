from __future__ import annotations

import base64

import pytest
from httpx import ASGITransport, AsyncClient


XSD = """<?xml version="1.0" encoding="UTF-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <xs:element name="Order">
    <xs:complexType>
      <xs:sequence>
        <xs:element name="Id" type="xs:integer"/>
        <xs:element name="Customer" type="xs:string"/>
      </xs:sequence>
    </xs:complexType>
  </xs:element>
</xs:schema>
"""


def _b64(s: str) -> str:
    return base64.b64encode(s.encode("utf-8")).decode("ascii")


async def test_validate_well_formed_only_passes(patched_app):
    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/iflow/validate-xml",
            json={"xml": "<Order><Id>1</Id><Customer>X</Customer></Order>"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["valid"] is True
    assert body["errors"] == []


async def test_validate_reports_wellformedness_failure(patched_app):
    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/api/v1/iflow/validate-xml", json={"xml": "<unclosed>"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False
    assert body["errors"][0]["level"] == "wellformedness"


async def test_validate_required_fields(patched_app):
    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/iflow/validate-xml",
            json={
                "xml": "<Order><Id>1</Id></Order>",
                "required_fields": ["/Order/Customer"],
            },
        )
    body = resp.json()
    assert body["valid"] is False
    assert any(e["level"] == "required_field" for e in body["errors"])


async def test_validate_xsd_failure(patched_app):
    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/iflow/validate-xml",
            json={
                "xml": "<Order><Id>abc</Id><Customer>X</Customer></Order>",
                "xsd_base64": _b64(XSD),
            },
        )
    body = resp.json()
    assert body["valid"] is False
    assert any(e["level"] == "xsd" for e in body["errors"])
