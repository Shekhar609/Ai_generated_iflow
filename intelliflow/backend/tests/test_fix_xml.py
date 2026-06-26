from __future__ import annotations

import base64
import json
from types import SimpleNamespace

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


def _fake_completion(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20, total_tokens=30),
    )


class FakeChat:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    async def create(self, **_kwargs):
        self.calls += 1
        return _fake_completion(self._responses.pop(0))


class FakeOpenAI:
    def __init__(self, responses):
        self.chat = SimpleNamespace(completions=FakeChat(responses))


class StubChunk:
    def __init__(self, source, chunk_id, text):
        self.source = source
        self.chunk_id = chunk_id
        self.text = text


@pytest.fixture
def patch_fixer(monkeypatch):
    def _install(responses):
        from app.services import error_fixer as fx_mod
        fake = FakeOpenAI(responses)
        monkeypatch.setattr(fx_mod, "_client", lambda: fake)

        async def fake_retrieve(_q):
            return [StubChunk("validation/common_xsd_errors.md", "0001", "fix-xml chunk")], None

        monkeypatch.setattr(fx_mod, "_retrieve", fake_retrieve)
        return fake
    return _install


async def test_fix_xml_returns_corrected_payload(patched_app, patch_fixer):
    corrected = "<Order><Id>1</Id><Customer>X</Customer></Order>"
    patch_fixer([
        json.dumps({
            "root_cause": "Id must be integer.",
            "corrected_xml": corrected,
            "citations": [{"source": "validation/common_xsd_errors.md", "chunk_id": "0001"}],
        })
    ])

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/iflow/fix-xml",
            json={
                "xml": "<Order><Id>abc</Id><Customer>X</Customer></Order>",
                "error_message": "Id is not a valid integer",
                "xsd_base64": _b64(XSD),
            },
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["corrected_xml"] == corrected
    assert body["still_invalid"] is False
    assert "diff" in body and body["diff"]


async def test_fix_xml_flags_still_invalid(patched_app, patch_fixer):
    # Returns a "corrected" payload that itself still fails validation.
    bad = "<Order><Id>abc</Id><Customer>X</Customer></Order>"
    patch_fixer([
        json.dumps({
            "root_cause": "diagnosis",
            "corrected_xml": bad,
            "citations": [],
        })
    ])
    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/iflow/fix-xml",
            json={
                "xml": "<Order/>",
                "error_message": "Id missing",
                "xsd_base64": _b64(XSD),
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["still_invalid"] is True
    assert body["remaining_errors"]
