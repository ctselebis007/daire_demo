"""In-memory tenant config cache, invalidated by a change stream on `tenants`."""

from __future__ import annotations

import asyncio
import logging
import time

from pymongo.errors import PyMongoError

from .db import SetupIncomplete, mongo

log = logging.getLogger("dare")
_SAFETY_TTL = 300


class TenantCache:
    def __init__(self) -> None:
        self._data: dict[str, tuple[float, dict]] = {}
        self._task: asyncio.Task | None = None
        self.doc_counts: dict[tuple[str, int], tuple[float, int]] = {}

    async def get(self, tenant_id: str) -> dict | None:
        hit = self._data.get(tenant_id)
        if hit and time.monotonic() - hit[0] < _SAFETY_TTL:
            return hit[1]
        db = await mongo.db()
        doc = await db["tenants"].find_one({"_id": tenant_id})
        if doc:
            self._data[tenant_id] = (time.monotonic(), doc)
        else:
            self._data.pop(tenant_id, None)
        return doc

    def invalidate(self, tenant_id: str | None = None) -> None:
        if tenant_id is None:
            self._data.clear()
            self.doc_counts.clear()
        else:
            self._data.pop(tenant_id, None)
            for k in [k for k in self.doc_counts if k[0] == tenant_id]:
                self.doc_counts.pop(k, None)

    async def active_doc_count(self, tenant_id: str, version: int) -> int:
        key = (tenant_id, version)
        hit = self.doc_counts.get(key)
        if hit and time.monotonic() - hit[0] < 60:
            return hit[1]
        db = await mongo.db()
        n = await db["documents"].count_documents({"tenantId": tenant_id, "datasetVersion": version, "status": 1})
        self.doc_counts[key] = (time.monotonic(), n)
        return n

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._watch(), name="tenant-cache-watch")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    async def _watch(self) -> None:
        resume = None
        while True:
            try:
                db = await mongo.db()
                async with await db["tenants"].watch(resume_after=resume) as stream:
                    async for change in stream:
                        resume = stream.resume_token
                        key = (change.get("documentKey") or {}).get("_id")
                        self.invalidate(key)
            except asyncio.CancelledError:
                raise
            except SetupIncomplete:
                await asyncio.sleep(5)
            except PyMongoError as exc:
                log.warning("tenant change stream error, retrying: %s", exc.__class__.__name__)
                resume = None
                self.invalidate()
                await asyncio.sleep(5)


tenant_cache = TenantCache()
