from __future__ import annotations

from types import SimpleNamespace

from app.services.prompt import build_prompt


def _chunk(source: str, chunk_id: str, text: str = "stub"):
    return SimpleNamespace(source=source, chunk_id=chunk_id, text=text)


def test_build_prompt_includes_user_prompt_and_chunks():
    prompt = build_prompt(
        "Build a flow that posts to Salesforce",
        [_chunk("sap_cpi_components/https_sender.md", "0001", "HTTPS Sender body")],
    )
    assert "Build a flow that posts to Salesforce" in prompt
    assert "sap_cpi_components/https_sender.md :: 0001" in prompt
    assert "HTTPS Sender body" in prompt


def test_build_prompt_clarifies_sender_vs_receiver():
    """Lock in the directional-naming clarification.

    Without this, the model has historically labelled outbound HTTPS calls as
    'HTTPS Sender', because the names are counter-intuitive (iFlow-perspective,
    not data-flow-arrow perspective).
    """
    prompt = build_prompt("anything", [])
    # Mid-prompt rule block
    assert "named after the EXTERNAL system's ROLE" in prompt
    assert "External system SENDS a request to iFlow" in prompt
    assert "External system RECEIVES a request from iFlow" in prompt
    assert "outbound HTTPS call to Salesforce/REST as \"HTTPS Sender\"" in prompt
    assert "such outbound calls are \"HTTPS Receiver\"" in prompt
    # Final-mile check that fires after the user prompt (recency-bias safeguard)
    assert "FINAL CHECK BEFORE YOU EMIT THE JSON" in prompt
    assert 'those three destinations are "<protocol> Receiver" components' in prompt


def test_build_prompt_appends_validation_error_on_retry():
    prompt = build_prompt(
        "x",
        [],
        validation_error="adapter_not_whitelisted: Telepathy Sender",
    )
    assert "previous response failed validation" in prompt
    assert "Telepathy Sender" in prompt
