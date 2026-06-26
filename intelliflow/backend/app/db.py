from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection, AsyncIOMotorDatabase
from pymongo import DESCENDING

from .config import get_settings

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        settings = get_settings()
        _client = AsyncIOMotorClient(settings.mongodb_uri)
    return _client


def get_db() -> AsyncIOMotorDatabase:
    global _db
    if _db is None:
        settings = get_settings()
        _db = get_client()[settings.mongodb_db_name]
    return _db


def flows_collection() -> AsyncIOMotorCollection:
    return get_db()["flows"]


async def ensure_indexes() -> None:
    await flows_collection().create_index([("created_at", DESCENDING)])


async def close_client() -> None:
    global _client, _db
    if _client is not None:
        _client.close()
    _client = None
    _db = None
