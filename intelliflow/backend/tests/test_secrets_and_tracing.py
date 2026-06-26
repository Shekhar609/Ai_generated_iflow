from __future__ import annotations

import logging

from app.services import secrets as sec_mod
from app.services.secrets import (
    EnvSecretsProvider,
    SecretsProvider,
    get_secret,
    set_secrets_provider,
)
from app.services.tracing import (
    configure_logging,
    new_request_id,
    redact,
    set_request_id,
    timed_step,
)


def test_env_provider_reads_env(monkeypatch):
    monkeypatch.setenv("FOO_TEST_SECRET", "value-123")
    assert EnvSecretsProvider().get("FOO_TEST_SECRET") == "value-123"


def test_pluggable_provider(monkeypatch):
    class Stub:
        def get(self, key):
            return "stub-" + key

    original = sec_mod.get_secrets_provider()
    try:
        set_secrets_provider(Stub())
        assert get_secret("anything") == "stub-anything"
    finally:
        set_secrets_provider(original)


def test_redact_strips_openai_and_anthropic_keys():
    text = "key=sk-abcdefghijklmnop and ant=sk-ant-abcdefghijklmnop"
    redacted = redact(text)
    assert "sk-abcdef" not in redacted
    assert "sk-ant-abcdef" not in redacted
    assert "[REDACTED]" in redacted


def test_no_keys_in_logs(caplog):
    configure_logging()
    with caplog.at_level(logging.INFO):
        logging.getLogger("intelliflow.test").info("token=sk-abcdefghijklmnop tail")
    leaked = [r for r in caplog.records if "sk-abcdef" in r.getMessage()]
    assert not leaked


def test_request_id_propagates_inside_timed_step(caplog):
    configure_logging()
    rid = new_request_id()
    with caplog.at_level(logging.INFO, logger="intelliflow.trace"):
        with timed_step("unit_step", note="x"):
            pass
    set_request_id(None)
    lines = [r.getMessage() for r in caplog.records if "unit_step" in r.getMessage()]
    assert lines
    assert rid in lines[0]
