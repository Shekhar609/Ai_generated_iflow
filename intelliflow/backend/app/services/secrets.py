from __future__ import annotations

import os
from typing import Protocol


class SecretsProvider(Protocol):
    def get(self, key: str) -> str | None: ...


class EnvSecretsProvider:
    def get(self, key: str) -> str | None:
        return os.environ.get(key)


_provider: SecretsProvider = EnvSecretsProvider()


def get_secrets_provider() -> SecretsProvider:
    return _provider


def set_secrets_provider(provider: SecretsProvider) -> None:
    global _provider
    _provider = provider


def get_secret(key: str) -> str | None:
    return _provider.get(key)
