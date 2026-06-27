from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient


CITATION = {"source": "sap_cpi_components/https_sender.md", "chunk_id": "0001"}
COMPOSITE_CHUNK_ID = f"{CITATION['source']}::{CITATION['chunk_id']}"


VALID_IFLOW = {
    "flow_name": "Customer Sync",
    "description": "Sync customer data from S/4HANA to Salesforce",
    "components": [
        {
            "id": "c1",
            "type": "HTTPS Sender",
            "config": {"address": "/customer"},
            "purpose": "Receive customer payload",
            "citations": [CITATION],
        },
        {
            "id": "c2",
            "type": "Message Mapping",
            "config": {"mapping": "Customer_to_SF"},
            "purpose": "Map S/4 to Salesforce schema",
            "citations": [CITATION],
        },
        {
            "id": "c3",
            "type": "SOAP Receiver",
            "config": {"endpoint": "https://salesforce/api"},
            "purpose": "Push to Salesforce",
            "citations": [CITATION],
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


class StubChunk:
    def __init__(self, source: str, chunk_id: str, text: str = "stub"):
        self.source = source
        self.chunk_id = chunk_id
        self.text = text
        self.score = 1.0
        self.metadata = {"source_file": source}

    def to_dict(self):
        return {"chunk_id": self.chunk_id, "source": self.source, "text": self.text, "score": self.score, "metadata": self.metadata}


@pytest.fixture
def patch_generator(monkeypatch):
    """Install a fake OpenAI client + stub retriever + permissive validators."""

    def _install(payloads, *, retriever_chunks=None):
        from app.services import iflow_generator as gen_mod
        from app.rag import retriever as ret_mod
        from app.rag import validators as val_mod

        fake_openai = FakeOpenAIClient(payloads)
        monkeypatch.setattr(gen_mod, "_openai", lambda: fake_openai)

        chunks = retriever_chunks or [StubChunk(CITATION["source"], CITATION["chunk_id"])]

        async def fake_retrieve(_prompt):
            return list(chunks), None

        monkeypatch.setattr(ret_mod, "retrieve", fake_retrieve)

        # Whitelist: just the Phase 1 enum (no Chroma access in tests).
        monkeypatch.setattr(val_mod, "_gather_chroma_adapter_types", lambda: set())

        # Known chunk ids: accept the composite the stub retriever returned.
        known = {f"{c.source}::{c.chunk_id}" for c in chunks}
        monkeypatch.setattr(val_mod, "_gather_known_chunk_ids", lambda ids: known)

        return fake_openai

    return _install


async def test_generate_happy_path(patched_app, patch_generator, fake_flows):
    fake = patch_generator([json.dumps(VALID_IFLOW)])

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
    # Every component must carry citations.
    for comp in body["flow"]["components"]:
        assert comp["citations"], comp


@pytest.mark.parametrize("bad_prompt", ["short", "x" * 4001])
async def test_generate_rejects_bad_prompt_length(patched_app, patch_generator, bad_prompt):
    patch_generator([json.dumps(VALID_IFLOW)])

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/api/v1/iflow/generate", json={"prompt": bad_prompt})

    assert resp.status_code == 422


async def test_generate_retries_once_then_422(patched_app, patch_generator):
    # First payload has invalid type (hallucinated adapter); second is also broken.
    broken = dict(VALID_IFLOW)
    broken["components"] = [
        {
            "id": "x", "type": "Telepathy Sender", "config": {}, "purpose": "fake",
            "citations": [CITATION],
        }
    ]
    fake = patch_generator([json.dumps(broken), json.dumps(broken)])

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/iflow/generate",
            json={"prompt": "A valid prompt that is long enough to pass the length check."},
        )

    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["attempts"] == 2
    assert any(i["code"] == "adapter_not_whitelisted" for i in detail["issues"])
    assert fake.chat.completions.calls == 2


async def test_generate_download_xml_streams_iflw_with_flow_id_header(patched_app, patch_generator, fake_flows):
    fake = patch_generator([json.dumps(VALID_IFLOW)])

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/iflow/generate-download?format=xml",
            json={"prompt": "Build a customer sync from S/4HANA to Salesforce"},
        )

    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("application/xml")
    assert resp.headers["content-disposition"].endswith('.iflw"')
    flow_id = resp.headers["x-flow-id"]
    assert flow_id and flow_id in fake_flows.docs  # persisted before streaming
    body = resp.content.decode("utf-8")
    assert "bpmn2:definitions" in body
    assert "bpmn2:process" in body
    assert fake.chat.completions.calls == 1


async def test_generate_download_defaults_to_xml(patched_app, patch_generator, fake_flows):
    patch_generator([json.dumps(VALID_IFLOW)])
    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/iflow/generate-download",
            json={"prompt": "Build a customer sync from S/4HANA to Salesforce"},
        )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/xml")


async def test_generate_download_json_streams_json_attachment(patched_app, patch_generator, fake_flows):
    patch_generator([json.dumps(VALID_IFLOW)])
    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/iflow/generate-download?format=json",
            json={"prompt": "Build a customer sync from S/4HANA to Salesforce"},
        )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.headers["content-disposition"].endswith('.json"')
    body = json.loads(resp.content)
    assert body["flow"]["flow_name"] == "Customer Sync"


async def test_generate_download_propagates_generator_error_as_422(patched_app, patch_generator):
    broken = dict(VALID_IFLOW)
    broken["components"] = [
        {"id": "x", "type": "Telepathy Sender", "config": {}, "purpose": "fake",
         "citations": [CITATION]}
    ]
    patch_generator([json.dumps(broken), json.dumps(broken)])

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/iflow/generate-download?format=xml",
            json={"prompt": "A valid prompt that is long enough to pass the length check."},
        )
    assert resp.status_code == 422


async def test_generate_retries_succeeds_on_second_attempt(patched_app, patch_generator):
    bad_payload = json.dumps({"flow_name": "incomplete"})
    fake = patch_generator([bad_payload, json.dumps(VALID_IFLOW)])

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/iflow/generate",
            json={"prompt": "A valid prompt that is long enough to pass the length check."},
        )

    assert resp.status_code == 200, resp.text
    assert fake.chat.completions.calls == 2
