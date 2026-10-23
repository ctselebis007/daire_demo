"""MongoDB client lifecycle and capability detection."""

from __future__ import annotations

import asyncio
import logging

from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import CollectionInvalid, PyMongoError

from .settings import Settings, store

log = logging.getLogger("dare")

COLLECTIONS = (
    "tenants",
    "documents",
    "ingestion_jobs",
    "ingestion_payloads",
    "feedback_events",
    "api_audits",
    "dare_meta",
)


class SetupIncomplete(RuntimeError):
    pass


class _Mongo:
    def __init__(self) -> None:
        self._client: AsyncMongoClient | None = None
        self._key: tuple[str, str] | None = None
        self._lock = asyncio.Lock()
        self.capabilities: dict = {}

    async def client(self) -> AsyncMongoClient:
        s = store.current
        if not s.mongo_ready:
            raise SetupIncomplete("MongoDB URI and database name are not configured")
        key = (s.mongodb_uri, s.db_name)
        async with self._lock:
            if self._client is None or self._key != key:
                await self._close_locked()
                # Single long-lived client; small POC concurrency so driver default pool (100) is ample.
                # serverSelectionTimeoutMS kept short so the Setup "Test" button fails fast.
                self._client = AsyncMongoClient(
                    s.mongodb_uri, appname="dare-mdb", serverSelectionTimeoutMS=10_000, tz_aware=True
                )
                self._key = key
                self.capabilities = {}
        return self._client

    async def db(self) -> AsyncDatabase:
        c = await self.client()
        return c[store.current.db_name]

    async def _close_locked(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def close(self) -> None:
        async with self._lock:
            await self._close_locked()

    async def detect_capabilities(self) -> dict:
        db = await self.db()
        await db.command("ping")
        info = await db.command("buildInfo")
        version = info.get("version", "0.0.0")
        major, minor = (int(x) for x in version.split(".")[:2])
        caps = {
            "version": version,
            "rankFusion": (major, minor) >= (8, 0),
            "scoreFusion": (major, minor) >= (8, 2),
            "searchIndexes": False,
            "changeStreams": False,
        }
        try:
            await ensure_collections(db)
            cursor = await db["documents"].list_search_indexes()
            await cursor.to_list(None)
            caps["searchIndexes"] = True
        except PyMongoError as exc:
            caps["searchIndexesError"] = str(exc)[:300]
        try:
            hello = await db.command("hello")
            caps["changeStreams"] = bool(hello.get("setName") or hello.get("msg") == "isdbgrid")
        except PyMongoError:
            pass
        self.capabilities = caps
        return caps


async def ensure_collections(db: AsyncDatabase) -> list[str]:
    existing = set(await db.list_collection_names())
    created = []
    for name in COLLECTIONS:
        if name not in existing:
            try:
                await db.create_collection(name)
                created.append(name)
            except CollectionInvalid:
                pass
    return created


mongo = _Mongo()


def settings() -> Settings:
    return store.current
