from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

# Ensure backend/ is on sys.path when tests are invoked from any cwd.
BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017")
os.environ.setdefault("LLM_MODEL", "gpt-4-turbo-test")
os.environ.setdefault("LLM_FALLBACK_MODEL", "claude-sonnet-4-6-test")
os.environ.setdefault("LLM_REWRITER_MODEL", "claude-haiku-4-5-test")
os.environ.setdefault("CHROMA_PERSIST_DIR", str(Path(tempfile.gettempdir()) / "intelliflow_test_chroma"))


class FakeFlowsCollection:
    """In-memory async stand-in for the Motor flows collection used in tests."""

    def __init__(self) -> None:
        self.docs: dict[str, dict[str, Any]] = {}

    async def insert_one(self, doc: dict[str, Any]) -> Any:
        self.docs[doc["_id"]] = dict(doc)

        class _Result:
            inserted_id = doc["_id"]

        return _Result()

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        _id = query.get("_id")
        doc = self.docs.get(_id)
        return None if doc is None else dict(doc)

    async def find_one_and_update(
        self,
        query: dict[str, Any],
        update: dict[str, Any],
        return_document: Any = None,
    ) -> dict[str, Any] | None:
        _id = query.get("_id")
        if _id not in self.docs:
            return None
        for key, value in update.get("$set", {}).items():
            self.docs[_id][key] = value
        return dict(self.docs[_id])

    async def count_documents(self, _query: dict[str, Any]) -> int:
        return len(self.docs)

    def find(self, _query: dict[str, Any], projection: dict[str, Any] | None = None):
        docs = [dict(d) for d in self.docs.values()]
        if projection:
            for d in docs:
                for key, include in projection.items():
                    if include == 0 and key in d:
                        del d[key]
        return _FakeCursor(docs)

    async def create_index(self, *_args: Any, **_kwargs: Any) -> str:
        return "created_at_-1"


class _FakeCursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs
        self._skip = 0
        self._limit: int | None = None

    def sort(self, key: str, direction: int) -> "_FakeCursor":
        reverse = direction == -1
        self._docs = sorted(self._docs, key=lambda d: d.get(key, datetime.min), reverse=reverse)
        return self

    def skip(self, n: int) -> "_FakeCursor":
        self._skip = n
        return self

    def limit(self, n: int) -> "_FakeCursor":
        self._limit = n
        return self

    def __aiter__(self):
        end = None if self._limit is None else self._skip + self._limit
        self._iter = iter(self._docs[self._skip:end])
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


@pytest.fixture
def fake_flows():
    return FakeFlowsCollection()


@pytest.fixture
def patched_app(monkeypatch, fake_flows):
    """Build a FastAPI app with the flows collection swapped for the in-memory fake.

    Also disables the slowapi rate limiter so test runs don't trip the 10/min cap when
    the test file calls /generate repeatedly.
    """

    from app import db as db_module
    from app.routers import iflow as iflow_router
    from app.services.limiter import limiter

    async def noop_ensure_indexes() -> None:
        return None

    async def noop_close_client() -> None:
        return None

    monkeypatch.setattr(db_module, "ensure_indexes", noop_ensure_indexes)
    monkeypatch.setattr(db_module, "close_client", noop_close_client)
    monkeypatch.setattr(db_module, "flows_collection", lambda: fake_flows)
    monkeypatch.setattr(iflow_router, "flows_collection", lambda: fake_flows)

    limiter.enabled = False

    from app.main import app

    return app


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
