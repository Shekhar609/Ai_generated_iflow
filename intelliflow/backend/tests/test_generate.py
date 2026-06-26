from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient


VALID_IFLOW = {
    "flow_name": "Customer Sync",
    "description": "Sync customer data from S/4HANA to Salesforce",
    "components": [
        {
            "id": "c1",
            "type": "HTTPS Sender",
            "config": {"address": "/customer"},
            "purpose": "Receive customer payload",
        },
        {
            "id": "c2",
            "type": "Message Mapping",
            "config": {"mapping": "Customer_to_SF"},
            "purpose": "Map S/4 to Salesforce schema",
        },
        {
            "id": "c3",
            "type": "SOAP Receiver",
            "config": {"endpoint": "https://salesforce/api"},
            "purpose": "Push to Salesforce",
        },
    ],
    "connections": [
        {"from": "c1", "to": "c2"},
        {"from": "c2", "to": "c3"},
    ],
    "xml_request": "<Request><Customer><Id>1</Id></Customer></Request>",
    "xml_response": "<Response><Status>OK</Status></Response>",
    "mapping_rules": [],
    "error_handling": {},
}


def _fake_completion(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=200, total_tokens=300),
    )


class FakeChatCompletions:
    def __init__(self, payloads):
        self._payloads = list(payloads)
        self.calls = 0

    async def create(self, **_kwargs):
        self.calls += 1
        if not self._payloads:
            raise AssertionError("FakeChatCompletions exhausted")
        content = self._payloads.pop(0)
        return _fake_completion(content)


class FakeOpenAIClient:
    def __init__(self, payloads):
        self.chat = SimpleNamespace(completions=FakeChatCompletions(payloads))


@pytest.fixture
def patch_openai(monkeypatch):
    """Returns a function that installs a FakeOpenAIClient with the given payloads."""

    def _install(payloads):
        from app.services import llm as llm_module

        fake = FakeOpenAIClient(payloads)
        monkeypatch.setattr(llm_module, "get_openai_client", lambda: fake)
        return fake

    return _install


async def test_generate_happy_path(patched_app, patch_openai, fake_flows):
    fake = patch_openai([json.dumps(VALID_IFLOW)])

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/iflow/generate",
            json={"prompt": "Build a customer sync from S/4HANA to Salesforce"},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["flow"]["flow_name"] == "Customer Sync"
    assert "flow_id" in body
    assert fake.chat.completions.calls == 1
    assert body["flow_id"] in fake_flows.docs


@pytest.mark.parametrize("bad_prompt", ["short", "x" * 4001])
async def test_generate_rejects_bad_prompt_length(patched_app, patch_openai, bad_prompt):
    patch_openai([json.dumps(VALID_IFLOW)])

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/api/v1/iflow/generate", json={"prompt": bad_prompt})

    assert resp.status_code == 422


async def test_generate_retries_once_then_502(patched_app, patch_openai):
    bad_payload = json.dumps({"flow_name": "x"})  # missing required fields
    fake = patch_openai([bad_payload, bad_payload])

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/iflow/generate",
            json={"prompt": "A valid prompt that is long enough to pass the length check."},
        )

    assert resp.status_code == 502, resp.text
    detail = resp.json()["detail"]
    assert detail["attempts"] == 2
    assert fake.chat.completions.calls == 2


async def test_generate_retries_succeeds_on_second_attempt(patched_app, patch_openai):
    bad_payload = json.dumps({"flow_name": "incomplete"})
    fake = patch_openai([bad_payload, json.dumps(VALID_IFLOW)])

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/iflow/generate",
            json={"prompt": "A valid prompt that is long enough to pass the length check."},
        )

    assert resp.status_code == 200, resp.text
    assert fake.chat.completions.calls == 2
