"""Setup and Admin routes (local admin token required)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pymongo.errors import PyMongoError

from . import llm, voyage
from .bench import run_bench
from .db import mongo
from .indexes import create_db_indexes, create_or_update_search_index, index_status
from .ingestion import purge_stale_versions
from .jsonutil import j
from .security import require_token
from .seed_data import generate_records
from .seeder import SEED_TENANT_IDS, drop_seed, seed_jobs, start_seed
from .settings import redact_uri, store
from .tenant_cache import tenant_cache

router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])


def _safe_err(exc: Exception) -> str:
    return redact_uri(f"{exc.__class__.__name__}: {str(exc)[:400]}")


# ---------------------------------------------------------------- setup

@router.get("/setup")
async def get_setup() -> dict:
    return {"settings": store.masked(), "capabilities": mongo.capabilities}


@router.put("/setup")
async def put_setup(patch: dict) -> dict:
    before = (store.current.mongodb_uri, store.current.db_name)
    try:
        store.update(patch)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if (store.current.mongodb_uri, store.current.db_name) != before:
        await tenant_cache.stop()
        await mongo.close()
        tenant_cache.invalidate()
        tenant_cache.start()
    return {"settings": store.masked()}


@router.post("/setup/test/{target}")
async def test_setup(target: str) -> dict:
    try:
        if target == "mongodb":
            caps = await mongo.detect_capabilities()
            ok = caps["searchIndexes"] and caps["rankFusion"]
            return {"ok": ok, "capabilities": caps}
        if target == "voyage":
            vec = await voyage.embed_query("ping")
            out = {"ok": len(vec) == store.current.embedding_dimensions, "model": store.current.embedding_model, "dimensions": len(vec)}
            if store.current.rerank_enabled:
                rr = await voyage.rerank("cloud migration", ["AWS landing zone migration", "Baking sourdough bread"], top_k=1)
                out["rerank"] = {"model": store.current.rerank_model, "top": rr[0]["index"] if rr else None, "ok": bool(rr) and rr[0]["index"] == 0}
            return out
        if target == "openai":
            reply = await llm.ping()
            return {"ok": bool(reply), "model": store.current.openai_model, "reply": reply[:20]}
    except Exception as exc:
        return {"ok": False, "error": _safe_err(exc)}
    raise HTTPException(404, "Unknown test target")


# ---------------------------------------------------------------- indexes

@router.post("/admin/indexes/db")
async def make_db_indexes() -> dict:
    db = await mongo.db()
    return {"results": await create_db_indexes(db, store.current.audit_ttl_days)}


@router.post("/admin/indexes/search")
async def make_search_index() -> dict:
    db = await mongo.db()
    return j(await create_or_update_search_index(db, "search", store.current.embedding_dimensions))


@router.post("/admin/indexes/vector")
async def make_vector_index() -> dict:
    db = await mongo.db()
    return j(await create_or_update_search_index(db, "vector", store.current.embedding_dimensions))


@router.get("/admin/indexes/status")
async def get_index_status() -> dict:
    db = await mongo.db()
    return j(await index_status(db, store.current.embedding_dimensions))


# ---------------------------------------------------------------- seed

@router.post("/admin/seed")
async def seed(opts: dict) -> dict:
    await mongo.db()
    n = int(opts.get("recordsPerTenant", 2000))
    if not 10 <= n <= 50_000:
        raise HTTPException(400, "recordsPerTenant must be between 10 and 50000")
    if any(job["status"] == "running" for job in seed_jobs.values()):
        raise HTTPException(409, "A seed job is already running")
    return {"seedJobId": start_seed(opts)}


@router.get("/admin/seed/{job_id}")
async def seed_status(job_id: str) -> dict:
    job = seed_jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Unknown seed job")
    return j(job)


@router.delete("/admin/seed")
async def remove_seed() -> dict:
    db = await mongo.db()
    return {"deleted": await drop_seed(db)}


@router.get("/admin/sample-records")
async def sample_records(tenantId: str, count: int = 100, seed: int = 42) -> dict:
    if tenantId not in SEED_TENANT_IDS:
        raise HTTPException(404, "Sample generator only exists for seed tenants")
    if not 1 <= count <= 5000:
        raise HTTPException(400, "count must be 1..5000")
    return {"tenantId": tenantId, "records": generate_records(tenantId, count, seed)}


# ---------------------------------------------------------------- stats / maintenance

@router.get("/admin/stats")
async def stats() -> dict:
    db = await mongo.db()
    per_version = await (await db["documents"].aggregate([
        {"$group": {"_id": {"tenantId": "$tenantId", "datasetVersion": "$datasetVersion"}, "count": {"$sum": 1}}},
        {"$sort": {"_id.tenantId": 1, "_id.datasetVersion": 1}},
    ])).to_list(None)
    tenants = await db["tenants"].find({}, {"name": 1, "activeDatasetVersion": 1, "previousDatasetVersion": 1, "swappedAt": 1}).to_list(None)
    colls = {}
    for name in ("documents", "tenants", "ingestion_jobs", "feedback_events", "api_audits"):
        try:
            s = await (await db[name].aggregate([{"$collStats": {"storageStats": {}}}])).to_list(1)
            ss = s[0]["storageStats"] if s else {}
            colls[name] = {"count": ss.get("count", 0), "storageSize": ss.get("storageSize", 0),
                           "totalIndexSize": ss.get("totalIndexSize", 0), "avgObjSize": ss.get("avgObjSize", 0)}
        except PyMongoError:
            colls[name] = {"count": await db[name].estimated_document_count()}
    return j({
        "tenants": tenants,
        "documentsByVersion": [{**r["_id"], "count": r["count"]} for r in per_version],
        "collections": colls,
        "capabilities": mongo.capabilities,
    })


@router.post("/admin/purge")
async def purge() -> dict:
    db = await mongo.db()
    return {"purged": await purge_stale_versions(db)}


@router.post("/admin/bench/{tenant_id}")
async def bench(tenant_id: str, samples: int = 20) -> dict:
    tenant = await tenant_cache.get(tenant_id)
    if not tenant:
        raise HTTPException(404, "Unknown tenant")
    return await run_bench(tenant, samples)
