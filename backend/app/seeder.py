"""Synthetic data seeding job (runs through the real ingestion path)."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime

from pymongo.asynchronous.database import AsyncDatabase

from .db import ensure_collections, mongo
from .ingestion import process_records
from .seed_data import generate_audits, generate_feedback, generate_records, tenant_configs
from .tenant_cache import tenant_cache

log = logging.getLogger("dare")
SEED_TENANT_IDS = [t["_id"] for t in tenant_configs()]
CHUNK = 250

seed_jobs: dict[str, dict] = {}


def _now() -> datetime:
    return datetime.now(UTC)


async def upsert_tenants(db: AsyncDatabase, tenant_ids: list[str]) -> list[dict]:
    out = []
    for cfg in tenant_configs():
        if cfg["_id"] not in tenant_ids:
            continue
        body = {k: v for k, v in cfg.items() if k != "_id"}
        await db["tenants"].update_one(
            {"_id": cfg["_id"]},
            {
                "$set": {**body, "status": "active", "seed": True, "updatedAt": _now()},
                "$setOnInsert": {"activeDatasetVersion": 1, "nextDatasetVersion": 1, "createdAt": _now()},
                "$inc": {"configVersion": 1},
            },
            upsert=True,
        )
        tenant_cache.invalidate(cfg["_id"])
        out.append(await db["tenants"].find_one({"_id": cfg["_id"]}))
    return out


def start_seed(opts: dict) -> str:
    job_id = uuid.uuid4().hex[:12]
    seed_jobs[job_id] = {
        "id": job_id, "status": "running", "step": "starting", "options": opts,
        "progress": {}, "log": [], "startedAt": _now(), "completedAt": None, "error": None,
    }
    asyncio.create_task(_run(job_id, opts), name=f"seed-{job_id}")
    return job_id


def _log(job: dict, msg: str) -> None:
    job["log"].append(f"{_now().strftime('%H:%M:%S')} {msg}")
    job["log"] = job["log"][-200:]


async def _run(job_id: str, opts: dict) -> None:
    job = seed_jobs[job_id]
    try:
        db = await mongo.db()
        await ensure_collections(db)
        tenant_ids = [t for t in opts.get("tenants", SEED_TENANT_IDS) if t in SEED_TENANT_IDS] or SEED_TENANT_IDS
        n = int(opts.get("recordsPerTenant", 2000))
        seed = int(opts.get("randomSeed", 42))

        if opts.get("dropExisting"):
            job["step"] = "dropping existing seed data"
            await drop_seed(db)
            _log(job, "Dropped existing seed data")

        job["step"] = "tenants"
        tenants = await upsert_tenants(db, tenant_ids)
        _log(job, f"Upserted tenant configs: {', '.join(tenant_ids)}")

        all_records: dict[str, list[dict]] = {}
        for tenant in tenants:
            tid = tenant["_id"]
            records = generate_records(tid, n, seed)
            all_records[tid] = records
            prog = job["progress"][tid] = {"total": n, "done": 0, "processed": 0, "skipped": 0, "rejected": 0, "embedded": 0, "embeddingReused": 0}
            job["step"] = f"ingesting {tid}"
            ing_id = str(uuid.uuid4())
            await db["ingestion_jobs"].insert_one({
                "_id": ing_id, "tenantId": tid, "batchId": f"seed-{job_id}-{tid}", "mode": "upsert",
                "targetDatasetVersion": None, "status": "processing", "totalBatches": (n + CHUNK - 1) // CHUNK,
                "batchesCompleted": 0, "batches": [], "counts": {"received": n, "processed": 0, "skipped": 0, "rejected": 0, "embedded": 0, "embeddingReused": 0, "tokens": 0},
                "rejections": [], "errorDetails": None, "createdAt": _now(), "startedAt": _now(), "completedAt": None, "seed": True,
            })
            version = tenant["activeDatasetVersion"]
            for seq, start in enumerate(range(0, n, CHUNK), 1):
                chunk = records[start:start + CHUNK]
                res = await process_records(db, tenant, chunk, version, skip_unchanged=True, job_id=ing_id)
                rejections = res.pop("rejections")
                for k in ("processed", "skipped", "rejected", "embedded", "embeddingReused"):
                    prog[k] += res[k]
                prog["done"] += len(chunk)
                await db["ingestion_jobs"].update_one({"_id": ing_id}, {
                    "$inc": {**{f"counts.{k}": v for k, v in res.items() if k != "received"}, "batchesCompleted": 1},
                    "$push": {"batches": {"sequence": seq, **res, "completedAt": _now()}, "rejections": {"$each": rejections, "$slice": 500}},
                })
            await db["ingestion_jobs"].update_one({"_id": ing_id}, {"$set": {"status": "complete", "completedAt": _now()}})
            tenant_cache.invalidate(tid)
            _log(job, f"{tid}: processed {prog['processed']}, skipped {prog['skipped']} unchanged, embedded {prog['embedded']}, reused {prog['embeddingReused']}")

        if opts.get("feedback", True):
            job["step"] = "feedback events"
            per = int(opts.get("feedbackPerTenant", 2000))
            await db["feedback_events"].delete_many({"seed": True, "tenantId": {"$in": tenant_ids}})
            for tid, recs in all_records.items():
                docs = generate_feedback(tid, recs, per, seed)
                for i in range(0, len(docs), 1000):
                    await db["feedback_events"].insert_many(docs[i:i + 1000], ordered=False)
            _log(job, f"Inserted {per} feedback events per tenant")

        if opts.get("audits", True):
            job["step"] = "audit history"
            count = int(opts.get("auditCount", 2000))
            await db["api_audits"].delete_many({"seed": True})
            docs = generate_audits(tenant_ids, count, seed)
            for i in range(0, len(docs), 1000):
                await db["api_audits"].insert_many(docs[i:i + 1000], ordered=False)
            _log(job, f"Inserted {count} audit records spread over 120 days (TTL removes those past retention)")

        job["status"] = "complete"
        job["step"] = "done"
    except Exception as exc:
        log.exception("seed failed")
        job["status"] = "failed"
        job["error"] = f"{exc.__class__.__name__}: {str(exc)[:500]}"
        _log(job, f"FAILED: {job['error']}")
    finally:
        job["completedAt"] = _now()


async def drop_seed(db: AsyncDatabase) -> dict:
    res = {
        "documents": (await db["documents"].delete_many({"tenantId": {"$in": SEED_TENANT_IDS}})).deleted_count,
        "ingestion_jobs": (await db["ingestion_jobs"].delete_many({"tenantId": {"$in": SEED_TENANT_IDS}})).deleted_count,
        "ingestion_payloads": (await db["ingestion_payloads"].delete_many({"tenantId": {"$in": SEED_TENANT_IDS}})).deleted_count,
        "feedback_events": (await db["feedback_events"].delete_many({"seed": True})).deleted_count,
        "api_audits": (await db["api_audits"].delete_many({"seed": True})).deleted_count,
        "tenants": (await db["tenants"].delete_many({"_id": {"$in": SEED_TENANT_IDS}})).deleted_count,
    }
    tenant_cache.invalidate()
    return res
