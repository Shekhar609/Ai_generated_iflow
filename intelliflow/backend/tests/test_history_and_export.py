from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient


def _seed_doc(idx: int) -> dict:
    return {
        "_id": f"flow-{idx:03d}",
        "name": f"Flow {idx}",
        "tags": [],
        "prompt": "seed prompt for tests",
        "flow": {
            "flow_name": f"Flow {idx}",
            "description": "seed",
            "components": [
                {"id": "c1", "type": "HTTPS Sender", "config": {}, "purpose": "in"},
            ],
            "connections": [],
            "xml_request": "<r/>",
            "xml_response": "<r/>",
            "mapping_rules": [],
            "error_handling": {},
        },
        "created_at": datetime(2026, 1, idx % 28 + 1, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 1, idx % 28 + 1, tzinfo=timezone.utc),
    }


async def test_history_pagination_math(patched_app, fake_flows):
    for i in range(1, 26):  # 25 docs
        fake_flows.docs[f"flow-{i:03d}"] = _seed_doc(i)

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        page1 = await ac.get("/api/v1/iflow/history?page=1&limit=20")
        page2 = await ac.get("/api/v1/iflow/history?page=2&limit=20")

    assert page1.status_code == 200
    b1 = page1.json()
    assert b1["total"] == 25
    assert b1["page"] == 1
    assert len(b1["items"]) == 20

    assert page2.status_code == 200
    b2 = page2.json()
    assert b2["total"] == 25
    assert b2["page"] == 2
    assert len(b2["items"]) == 5


async def test_get_flow_404(patched_app):
    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/v1/iflow/does-not-exist")
    assert resp.status_code == 404


async def test_export_pdf_returns_501(patched_app, fake_flows):
    fake_flows.docs["flow-001"] = _seed_doc(1)

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/v1/iflow/flow-001/export?format=pdf")

    assert resp.status_code == 501


async def test_export_json_returns_attachment(patched_app, fake_flows):
    fake_flows.docs["flow-001"] = _seed_doc(1)

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/v1/iflow/flow-001/export?format=json")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    assert "attachment" in resp.headers["content-disposition"]


async def test_save_updates_name_and_tags(patched_app, fake_flows):
    fake_flows.docs["flow-001"] = _seed_doc(1)

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/iflow/save",
            json={"flow_id": "flow-001", "name": "Renamed", "tags": ["prod"]},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "Renamed"
    assert body["tags"] == ["prod"]
    assert fake_flows.docs["flow-001"]["name"] == "Renamed"


async def test_save_404(patched_app):
    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/iflow/save",
            json={"flow_id": "missing", "name": "x", "tags": []},
        )
    assert resp.status_code == 404
