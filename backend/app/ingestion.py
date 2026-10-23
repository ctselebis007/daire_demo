"""Ingestion: validation, templating, content-hash embedding reuse, bulk upserts, job worker,
and the versioned `full_replace` pointer swap."""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from bson.binary import Binary, BinaryVectorDtype
from pymongo import ReturnDocument, UpdateOne
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError, OperationFailure, PyMongoError

from . import voyage
from .db import SetupIncomplete, mongo
from .indexes import TEXT_INDEX, VECTOR_INDEX
from .settings import store
from .templating import TemplateError, render, stable_hash, validate

log = logging.getLogger("dare")

MAX_RECORDS_PER_BATCH = 1000
LEASE = timedelta(minutes=5)
SWAP_TIMEOUT = timedelta(minutes=20)
OPEN_STATES = ("queued", "processing", "awaiting_index")


class IngestError(ValueError):
    pass


def now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------- record processing

def _date_paths(tenant: dict) -> list[list[str]]:
    return [
        f["path"].split(".")[1:]
        for f in tenant.get("indexConfig", {}).get("filterFields", [])
        if f.get("type") == "date" and f["path"].startswith("metadata.")
    ]


def _coerce_dates(metadata: dict, paths: list[list[str]]) -> None:
    for parts in paths:
        node: Any = metadata
        for p in parts[:-1]:
            node = node.get(p) if isinstance(node, dict) else None
        if isinstance(node, dict) and isinstance(node.get(parts[-1]), str):
            try:
                node[parts[-1]] = datetime.fromisoformat(node[parts[-1]].replace("Z", "+00:00"))
            except ValueError:
                pass


def _apply_pipeline(tenant: dict, record: dict) -> dict:
    for step in tenant.get("dataPipeline", []):
        if step.get("step") == "normalize":
            for field in (step.get("config") or {}).get("lowercase", []):
                v = record.get(field)
                if isinstance(v, str):
                    record[field] = v.lower()
                elif isinstance(v, list):
                    record[field] = [x.lower() if isinstance(x, str) else x for x in v]
    return record


def _keyword_text(tenant: dict, record: dict) -> str:
    parts: list[str] = []
    for field in tenant.get("indexConfig", {}).get("keywordFields", []):
        v = record.get(field)
        if isinstance(v, list):
            parts.extend(str(x) for x in v)
        elif v is not None:
            parts.append(str(v))
    return " ".join(parts)


def to_bson_vector(vec: list[float]) -> Binary:
    return Binary.from_vector(vec, BinaryVectorDtype.FLOAT32)


def from_bson_vector(value: Any) -> list[float]:
    if isinstance(value, Binary):
        return list(value.as_vector().data)
    return list(value or [])


async def process_records(
    db: AsyncDatabase,
    tenant: dict,
    records: list[Any],
    version: int,
    *,
    skip_unchanged: bool,
    job_id: str | None = None,
    extra: dict | None = None,
) -> dict:
    s = store.current
    counts = {"received": len(records), "processed": 0, "skipped": 0, "rejected": 0, "embedded": 0, "embeddingReused": 0, "tokens": 0}
    rejections: list[dict] = []
    prepared: list[dict] = []
    date_paths = _date_paths(tenant)
    seen: set[str] = set()

    for raw in records:
        rid = raw.get("recordId") if isinstance(raw, dict) else None
        if not isinstance(rid, str) or not rid or len(rid) > 200:
            counts["rejected"] += 1
            rejections.append({"recordId": None, "errors": ["recordId (string) is required"]})
            continue
        if rid in seen:
            counts["rejected"] += 1
            rejections.append({"recordId": rid, "errors": ["duplicate recordId in batch"]})
            continue
        errors = validate(tenant["inputSchema"], raw)
        if errors:
            counts["rejected"] += 1
            rejections.append({"recordId": rid, "errors": errors})
            continue
        record = _apply_pipeline(tenant, dict(raw))
        try:
            embedding_text = render(tenant["embeddingInputTemplate"], record)
        except TemplateError as exc:
            counts["rejected"] += 1
            rejections.append({"recordId": rid, "errors": [str(exc)[:200]]})
            continue
        seen.add(rid)
        metadata = {k: v for k, v in record.items() if k != "recordId"}
        _coerce_dates(metadata, date_paths)
        prepared.append({
            "recordId": rid,
            "metadata": metadata,
            "embeddingText": embedding_text,
            "keywordText": _keyword_text(tenant, record),
            "contentHash": stable_hash(record),
            "embeddingHash": stable_hash(s.embedding_model, s.embedding_dimensions, embedding_text),
        })

    if not prepared:
        return {**counts, "rejections": rejections}

    versions = sorted({version, tenant.get("activeDatasetVersion", version)})
    existing_by_id: dict[str, dict] = {}
    reuse: dict[str, Binary] = {}
    cursor = db["documents"].find(
        {"tenantId": tenant["_id"], "datasetVersion": {"$in": versions}, "recordId": {"$in": [p["recordId"] for p in prepared]}},
        {"recordId": 1, "datasetVersion": 1, "contentHash": 1, "embeddingHash": 1, "embedding": 1},
    )
    async for d in cursor:
        if d["datasetVersion"] == version:
            existing_by_id[d["recordId"]] = d
        if d.get("embedding") is not None:
            reuse[d["embeddingHash"]] = d["embedding"]

    to_write: list[dict] = []
    for p in prepared:
        ex = existing_by_id.get(p["recordId"])
        if skip_unchanged and ex and ex.get("contentHash") == p["contentHash"]:
            counts["skipped"] += 1
            continue
        to_write.append(p)

    need_embed: list[dict] = []
    for p in to_write:
        cached = voyage.embedding_cache.get(p["embeddingHash"])
        if cached is not None:
            p["embedding"] = to_bson_vector(cached)
            counts["embeddingReused"] += 1
        elif p["embeddingHash"] in reuse:
            p["embedding"] = reuse[p["embeddingHash"]]
            counts["embeddingReused"] += 1
        else:
            need_embed.append(p)

    if need_embed:
        vectors, tokens = await voyage.embed([p["embeddingText"] for p in need_embed], "document")
        counts["tokens"] += tokens
        for p, vec in zip(need_embed, vectors, strict=True):
            voyage.embedding_cache.put(p["embeddingHash"], vec)
            p["embedding"] = to_bson_vector(vec)
        counts["embedded"] += len(need_embed)

    ts = now()
    ops = []
    for p in to_write:
        doc = {
            **p,
            "tenantId": tenant["_id"],
            "datasetVersion": version,
            "status": 1,
            "embeddingModel": s.embedding_model,
            "ingestJobId": job_id,
            "updatedAt": ts,
            **(extra or {}),
        }
        ops.append(UpdateOne(
            {"tenantId": tenant["_id"], "datasetVersion": version, "recordId": p["recordId"]},
            {"$set": doc, "$setOnInsert": {"createdAt": ts}},
            upsert=True,
        ))
    if ops:
        await db["documents"].bulk_write(ops, ordered=False)
    counts["processed"] = len(to_write)
    return {**counts, "rejections": rejections}


# ---------------------------------------------------------------- job submission

async def submit_batch(db: AsyncDatabase, tenant: dict, body: dict) -> dict:
    mode = body.get("mode", "upsert")
    if mode not in ("upsert", "full_replace"):
        raise IngestError("mode must be 'upsert' or 'full_replace'")
    records = body.get("records")
    if not isinstance(records, list) or not records:
        raise IngestError("records must be a non-empty array")
    if len(records) > MAX_RECORDS_PER_BATCH:
        raise IngestError(f"max {MAX_RECORDS_PER_BATCH} records per batch")
    batch_id = str(body.get("batchId") or uuid.uuid4())[:100]
    sequence = int(body.get("sequence", 1))
    total = int(body.get("totalBatches", 1))
    if not (1 <= sequence <= total <= 10_000):
        raise IngestError("require 1 <= sequence <= totalBatches")

    tid = tenant["_id"]
    job = await db["ingestion_jobs"].find_one({"tenantId": tid, "batchId": batch_id})
    if job is None:
        if mode == "full_replace":
            open_job = await db["ingestion_jobs"].find_one({"tenantId": tid, "mode": "full_replace", "status": {"$in": list(OPEN_STATES)}})
            if open_job:
                raise IngestError(f"full_replace job {open_job['_id']} is already in progress for this tenant")
            t = await db["tenants"].find_one_and_update(
                {"_id": tid}, {"$inc": {"nextDatasetVersion": 1}}, return_document=ReturnDocument.AFTER
            )
            target = t["nextDatasetVersion"]
        else:
            target = None
        job = {
            "_id": str(uuid.uuid4()),
            "tenantId": tid,
            "batchId": batch_id,
            "mode": mode,
            "targetDatasetVersion": target,
            "status": "queued",
            "totalBatches": total,
            "batchesCompleted": 0,
            "batches": [],
            "counts": {"received": 0, "processed": 0, "skipped": 0, "rejected": 0, "embedded": 0, "embeddingReused": 0, "tokens": 0},
            "rejections": [],
            "errorDetails": None,
            "createdAt": now(),
            "startedAt": None,
            "completedAt": None,
        }
        try:
            await db["ingestion_jobs"].insert_one(job)
        except DuplicateKeyError:
            job = await db["ingestion_jobs"].find_one({"tenantId": tid, "batchId": batch_id})
    if job["mode"] != mode or job["totalBatches"] != total:
        raise IngestError("mode/totalBatches do not match the existing job for this batchId")
    if job["status"] not in ("queued", "processing"):
        raise IngestError(f"job is already {job['status']}")
    try:
        await db["ingestion_payloads"].insert_one({
            "jobId": job["_id"], "tenantId": tid, "sequence": sequence, "records": records,
            "status": "pending", "createdAt": now(),
        })
    except DuplicateKeyError as exc:
        raise IngestError(f"sequence {sequence} already submitted for this batch") from exc
    await db["ingestion_jobs"].update_one({"_id": job["_id"]}, {"$inc": {"counts.received": len(records)}})
    return {"jobId": job["_id"], "batchId": batch_id, "sequence": sequence, "status": "accepted"}


# ---------------------------------------------------------------- worker

class IngestionWorker:
    def __init__(self, concurrency: int = 2) -> None:
        self.concurrency = concurrency
        self.tasks: list[asyncio.Task] = []
        self.owner = f"{os.getpid()}-{uuid.uuid4().hex[:6]}"

    def start(self) -> None:
        if any(not t.done() for t in self.tasks):
            return
        self.tasks = [asyncio.create_task(self._loop(i), name=f"ingest-{i}") for i in range(self.concurrency)]
        self.tasks.append(asyncio.create_task(self._sweeper(), name="version-sweeper"))
        self.tasks.append(asyncio.create_task(self._resume_swaps(), name="resume-swaps"))

    async def stop(self) -> None:
        for t in self.tasks:
            t.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks = []

    async def _loop(self, idx: int) -> None:
        while True:
            try:
                db = await mongo.db()
                ts = now()
                payload = await db["ingestion_payloads"].find_one_and_update(
                    {"$or": [{"status": "pending"}, {"status": "processing", "leaseExpiresAt": {"$lt": ts}}]},
                    {"$set": {"status": "processing", "leaseExpiresAt": ts + LEASE, "leaseOwner": self.owner}},
                    sort=[("createdAt", 1)],
                    return_document=ReturnDocument.AFTER,
                )
                if payload is None:
                    await asyncio.sleep(1.0)
                    continue
                await self._process(db, payload)
            except asyncio.CancelledError:
                raise
            except SetupIncomplete:
                await asyncio.sleep(5)
            except Exception:
                log.exception("ingestion worker %s error", idx)
                await asyncio.sleep(3)

    async def _process(self, db: AsyncDatabase, payload: dict) -> None:
        job = await db["ingestion_jobs"].find_one({"_id": payload["jobId"]})
        tenant = await db["tenants"].find_one({"_id": payload["tenantId"]})
        if job is None or tenant is None:
            await db["ingestion_payloads"].delete_one({"_id": payload["_id"]})
            return
        await db["ingestion_jobs"].update_one(
            {"_id": job["_id"], "status": "queued"}, {"$set": {"status": "processing", "startedAt": now()}}
        )
        version = job["targetDatasetVersion"] if job["mode"] == "full_replace" else tenant["activeDatasetVersion"]
        try:
            result = await process_records(
                db, tenant, payload["records"], version,
                skip_unchanged=job["mode"] == "upsert", job_id=job["_id"],
            )
        except Exception as exc:
            await db["ingestion_payloads"].update_one({"_id": payload["_id"]}, {"$set": {"status": "failed"}})
            await db["ingestion_jobs"].update_one(
                {"_id": job["_id"]},
                {"$set": {"status": "failed", "errorDetails": f"{exc.__class__.__name__}: {str(exc)[:500]}", "completedAt": now()}},
            )
            return
        await db["ingestion_payloads"].delete_one({"_id": payload["_id"]})
        rejections = result.pop("rejections")
        inc = {f"counts.{k}": v for k, v in result.items() if k != "received"}
        inc["batchesCompleted"] = 1
        updated = await db["ingestion_jobs"].find_one_and_update(
            {"_id": job["_id"]},
            {
                "$inc": inc,
                "$push": {
                    "batches": {"sequence": payload["sequence"], **result, "completedAt": now()},
                    "rejections": {"$each": rejections, "$slice": 500},
                },
            },
            return_document=ReturnDocument.AFTER,
        )
        if updated and updated["status"] == "processing" and updated["batchesCompleted"] >= updated["totalBatches"]:
            await self._finalize(db, updated)

    async def _finalize(self, db: AsyncDatabase, job: dict) -> None:
        if job["mode"] == "upsert":
            await db["ingestion_jobs"].update_one({"_id": job["_id"]}, {"$set": {"status": "complete", "completedAt": now()}})
            return
        await db["ingestion_jobs"].update_one({"_id": job["_id"]}, {"$set": {"status": "awaiting_index"}})
        asyncio.create_task(swap_when_indexed(job["_id"]), name=f"swap-{job['_id']}")

    async def _resume_swaps(self) -> None:
        while True:
            try:
                db = await mongo.db()
                async for job in db["ingestion_jobs"].find({"status": "awaiting_index"}, {"_id": 1}):
                    asyncio.create_task(swap_when_indexed(job["_id"]))
                return
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(5)

    async def _sweeper(self) -> None:
        while True:
            try:
                await purge_stale_versions(await mongo.db())
            except asyncio.CancelledError:
                raise
            except SetupIncomplete:
                pass
            except Exception:
                log.exception("version sweeper error")
            await asyncio.sleep(60)


# ---------------------------------------------------------------- versioned swap

async def _indexed_counts(db: AsyncDatabase, tenant_id: str, version: int, expected: int) -> tuple[int, int]:
    text = await (await db["documents"].aggregate([
        {"$searchMeta": {
            "index": TEXT_INDEX,
            "compound": {"filter": [
                {"equals": {"path": "tenantId", "value": tenant_id}},
                {"equals": {"path": "datasetVersion", "value": version}},
            ]},
            "count": {"type": "total"},
        }}
    ])).to_list(None)
    text_n = text[0]["count"]["total"] if text else 0

    sample = await db["documents"].find_one({"tenantId": tenant_id, "datasetVersion": version}, {"embedding": 1})
    if not sample:
        return text_n, 0
    limit = min(expected, 10_000)
    vec = await (await db["documents"].aggregate([
        {"$vectorSearch": {
            "index": VECTOR_INDEX, "path": "embedding", "queryVector": from_bson_vector(sample["embedding"]),
            "exact": True, "limit": limit,
            "filter": {"$and": [{"tenantId": tenant_id}, {"datasetVersion": version}]},
        }},
        {"$count": "n"},
    ])).to_list(None)
    vec_n = vec[0]["n"] if vec else 0
    return text_n, vec_n


async def swap_when_indexed(job_id: str) -> None:
    db = await mongo.db()
    job = await db["ingestion_jobs"].find_one({"_id": job_id})
    if not job or job["status"] != "awaiting_index":
        return
    tid, target = job["tenantId"], job["targetDatasetVersion"]
    expected = await db["documents"].count_documents({"tenantId": tid, "datasetVersion": target, "status": 1})
    deadline = now() + SWAP_TIMEOUT
    last = (0, 0)
    while now() < deadline:
        try:
            last = await _indexed_counts(db, tid, target, expected)
            await db["ingestion_jobs"].update_one(
                {"_id": job_id}, {"$set": {"indexProgress": {"expected": expected, "text": last[0], "vector": last[1], "checkedAt": now()}}}
            )
            if last[0] >= expected and last[1] >= min(expected, 10_000):
                break
        except OperationFailure as exc:
            await db["ingestion_jobs"].update_one(
                {"_id": job_id}, {"$set": {"indexProgress": {"error": str(exc)[:300], "checkedAt": now()}}}
            )
        await asyncio.sleep(3)
    else:
        await db["ingestion_jobs"].update_one(
            {"_id": job_id},
            {"$set": {"status": "failed", "completedAt": now(),
                      "errorDetails": f"Search indexes did not catch up (text {last[0]}, vector {last[1]} of {expected}); version not activated"}},
        )
        return

    tenant = await db["tenants"].find_one({"_id": tid})
    old = tenant["activeDatasetVersion"]
    res = await db["tenants"].update_one(
        {"_id": tid, "activeDatasetVersion": old},
        {"$set": {"activeDatasetVersion": target, "previousDatasetVersion": old, "swappedAt": now(), "updatedAt": now()}},
    )
    if res.modified_count != 1:
        await db["ingestion_jobs"].update_one(
            {"_id": job_id}, {"$set": {"status": "failed", "completedAt": now(), "errorDetails": "Concurrent swap detected"}}
        )
        return
    await db["ingestion_jobs"].update_one(
        {"_id": job_id},
        {"$set": {"status": "complete", "completedAt": now(), "swap": {"from": old, "to": target, "at": now()}}},
    )


async def rollback(db: AsyncDatabase, tenant_id: str) -> dict:
    t = await db["tenants"].find_one({"_id": tenant_id})
    if not t or t.get("previousDatasetVersion") is None:
        raise IngestError("No previous dataset version available to roll back to")
    cur, prev = t["activeDatasetVersion"], t["previousDatasetVersion"]
    res = await db["tenants"].update_one(
        {"_id": tenant_id, "activeDatasetVersion": cur, "previousDatasetVersion": prev},
        {"$set": {"activeDatasetVersion": prev, "previousDatasetVersion": cur, "swappedAt": now(), "updatedAt": now()}},
    )
    if res.modified_count != 1:
        raise IngestError("Tenant changed concurrently; retry")
    return {"activeDatasetVersion": prev, "previousDatasetVersion": cur}


async def purge_stale_versions(db: AsyncDatabase) -> dict:
    grace = timedelta(seconds=store.current.purge_grace_seconds)
    purged: dict[str, int] = {}
    async for t in db["tenants"].find({}, {"activeDatasetVersion": 1, "previousDatasetVersion": 1, "swappedAt": 1}):
        keep = {t.get("activeDatasetVersion")}
        prev = t.get("previousDatasetVersion")
        if prev is not None:
            swapped = t.get("swappedAt")
            if swapped and now() - swapped > grace:
                await db["tenants"].update_one({"_id": t["_id"], "previousDatasetVersion": prev}, {"$unset": {"previousDatasetVersion": ""}})
            else:
                keep.add(prev)
        async for j in db["ingestion_jobs"].find(
            {"tenantId": t["_id"], "status": {"$in": list(OPEN_STATES)}, "targetDatasetVersion": {"$ne": None}},
            {"targetDatasetVersion": 1},
        ):
            keep.add(j["targetDatasetVersion"])
        try:
            res = await db["documents"].delete_many({"tenantId": t["_id"], "datasetVersion": {"$nin": list(keep)}})
            if res.deleted_count:
                purged[t["_id"]] = res.deleted_count
        except PyMongoError:
            log.exception("purge failed for %s", t["_id"])
    return purged


worker = IngestionWorker()
