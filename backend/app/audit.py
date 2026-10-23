"""Async, off-critical-path audit writer with PII scrubbing. Retention via TTL index."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from .db import mongo

log = logging.getLogger("dare")

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"\+?\d[\d\s().-]{7,}\d")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
DEFAULT_PII = {"email", "phone", "ssn", "dob", "address"}


def scrub(value: Any, pii_fields: set[str]) -> Any:
    if isinstance(value, dict):
        return {k: ("***" if k.lower() in pii_fields else scrub(v, pii_fields)) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v, pii_fields) for v in value]
    if isinstance(value, str):
        return _SSN.sub("***-**-****", _PHONE.sub("***", _EMAIL.sub("***@***", value)))
    return value


class AuditWriter:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=10_000)
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="audit-writer")

    async def stop(self) -> None:
        if self._task:
            await self._flush_remaining()
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    def enqueue(self, doc: dict) -> None:
        try:
            self.queue.put_nowait(doc)
        except asyncio.QueueFull:
            log.warning("audit queue full; dropping audit %s", doc.get("requestId"))

    async def _write(self, batch: list[dict]) -> None:
        if not batch:
            return
        try:
            db = await mongo.db()
            await db["api_audits"].insert_many(batch, ordered=False)
        except Exception:
            log.exception("audit flush failed (%d docs)", len(batch))

    async def _flush_remaining(self) -> None:
        batch = []
        while not self.queue.empty():
            batch.append(self.queue.get_nowait())
        await self._write(batch)

    async def _run(self) -> None:
        while True:
            batch = [await self.queue.get()]
            deadline = asyncio.get_running_loop().time() + 0.5
            while len(batch) < 100:
                timeout = deadline - asyncio.get_running_loop().time()
                if timeout <= 0:
                    break
                try:
                    batch.append(await asyncio.wait_for(self.queue.get(), timeout))
                except TimeoutError:
                    break
            await self._write(batch)


audit_writer = AuditWriter()
