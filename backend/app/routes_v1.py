"""Platform API (/v1): tenants, ingestion, jobs, recommendations, search, feedback, audits."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .db import mongo
from .ingestion import rollback, submit_batch
from .jsonutil import j
from .recommend import compare_search, recommend
from .security import require_token
from .templating import check_schema, check_template
from .tenant_cache import tenant_cache

router = APIRouter(prefix="/v1", dependencies=[Depends(require_token)])
_TENANT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
_FILTER_TYPES = {"string", "string[]", "number", "date", "boolean"}
_OPS = {"eq", "ne", "in", "nin", "gt", "gte", "lt", "lte", "exists"}


async def _tenant(tenant_id: str) -> dict:
    t = await tenant_cache.get(tenant_id)
    if not t or t.get("status") != "active":
        raise HTTPException(404, f"Unknown tenant {tenant_id!r}")
    return t


def _safe_keys(value: Any, depth: int = 0) -> None:
    if depth > 10:
        raise HTTPException(400, "Document nested too deeply")
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str) or k.startswith("$") or "." in k:
                raise HTTPException(400, f"Invalid field name {k!r}")
            _safe_keys(v, depth + 1)
    elif isinstance(value, list):
        for v in value:
            _safe_keys(v, depth + 1)


# ---------------------------------------------------------------- tenants

@router.get("/tenants")
async def list_tenants() -> list[dict]:
    db = await mongo.db()
    rows = await db["tenants"].find({}, {"name": 1, "clientId": 1, "description": 1, "status": 1, "activeDatasetVersion": 1,
                                          "previousDatasetVersion": 1, "configVersion": 1, "sampleQueries": 1,
                                          "filterConfig": 1, "indexConfig": 1, "queryConfig": 1, "recommendationPipeline": 1}).sort("_id", 1).to_list(None)
    return j(rows)


@router.get("/tenants/{tenant_id}")
async def get_tenant(tenant_id: str) -> dict:
    db = await mongo.db()
    t = await db["tenants"].find_one({"_id": tenant_id})
    if not t:
        raise HTTPException(404, "Unknown tenant")
    return j(t)


def _validate_tenant(body: dict) -> None:
    # JSON Schemas are validated as Draft 2020-12; drop "$schema" so no $-prefixed field names are stored.
    if isinstance(body.get("inputSchema"), dict):
        body["inputSchema"].pop("$schema", None)
    if isinstance(body.get("queryConfig"), dict) and isinstance(body["queryConfig"].get("schema"), dict):
        body["queryConfig"]["schema"].pop("$schema", None)
    _safe_keys(body)
    for key, typ in (("name", str), ("inputSchema", dict), ("embeddingInputTemplate", str), ("indexConfig", dict),
                     ("queryConfig", dict), ("filterConfig", dict), ("recommendationPipeline", dict)):
        if not isinstance(body.get(key), typ):
            raise HTTPException(400, f"{key} is required ({typ.__name__})")
    try:
        check_schema(body["inputSchema"])
        check_schema(body["queryConfig"].get("schema") or {})
        check_template(body["embeddingInputTemplate"])
        check_template(body["queryConfig"].get("serializationTemplate") or "")
        if body["queryConfig"].get("keywordTemplate"):
            check_template(body["queryConfig"]["keywordTemplate"])
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    for f in body["indexConfig"].get("filterFields", []):
        if not re.fullmatch(r"metadata(\.[A-Za-z0-9_]+)+", str(f.get("path"))) or f.get("type") not in _FILTER_TYPES:
            raise HTTPException(400, f"Invalid filterField {f!r}")
    indexed = {f["path"] for f in body["indexConfig"].get("filterFields", [])}
    for a in body["filterConfig"].get("allowed", []):
        if a.get("field") not in indexed or not set(a.get("ops", [])) <= _OPS:
            raise HTTPException(400, f"filterConfig entry {a!r} must reference an indexed filterField with valid ops")


@router.put("/tenants/{tenant_id}")
async def put_tenant(tenant_id: str, body: dict) -> dict:
    if not _TENANT_ID.match(tenant_id):
        raise HTTPException(400, "tenantId must match ^[a-z0-9][a-z0-9-]{1,62}$")
    _validate_tenant(body)
    protected = {"_id", "activeDatasetVersion", "previousDatasetVersion", "nextDatasetVersion", "swappedAt", "createdAt", "configVersion", "updatedAt"}
    cfg = {k: v for k, v in body.items() if k not in protected}
    cfg.setdefault("status", "active")
    db = await mongo.db()
    now = datetime.now(UTC)
    await db["tenants"].update_one(
        {"_id": tenant_id},
        {"$set": {**cfg, "updatedAt": now}, "$setOnInsert": {"activeDatasetVersion": 1, "nextDatasetVersion": 1, "createdAt": now},
         "$inc": {"configVersion": 1}},
        upsert=True,
    )
    tenant_cache.invalidate(tenant_id)
    return j(await db["tenants"].find_one({"_id": tenant_id}))


@router.post("/tenants/{tenant_id}/rollback")
async def tenant_rollback(tenant_id: str) -> dict:
    await _tenant(tenant_id)
    db = await mongo.db()
    res = await rollback(db, tenant_id)
    tenant_cache.invalidate(tenant_id)
    return res


# ---------------------------------------------------------------- ingestion

@router.post("/tenants/{tenant_id}/records:batch", status_code=202)
async def ingest(tenant_id: str, body: dict) -> dict:
    tenant = await _tenant(tenant_id)
    _safe_keys(body.get("records"))
    db = await mongo.db()
    return await submit_batch(db, tenant, body)


@router.get("/jobs/{job_id}")
async def get_job(job_id: str) -> dict:
    db = await mongo.db()
    job = await db["ingestion_jobs"].find_one({"_id": job_id})
    if not job:
        raise HTTPException(404, "Unknown job")
    return j(job)


@router.get("/tenants/{tenant_id}/jobs")
async def tenant_jobs(tenant_id: str, limit: int = 20) -> list[dict]:
    db = await mongo.db()
    rows = await db["ingestion_jobs"].find({"tenantId": tenant_id}, {"rejections": 0, "batches": 0}) \
        .sort("createdAt", -1).limit(max(1, min(limit, 100))).to_list(None)
    return j(rows)


# ---------------------------------------------------------------- query

@router.post("/tenants/{tenant_id}/recommendations")
async def recommendations(tenant_id: str, body: dict, request: Request) -> dict:
    tenant = await _tenant(tenant_id)
    return j(await recommend(tenant, body, request.url.path))


@router.post("/tenants/{tenant_id}/search")
async def search(tenant_id: str, body: dict) -> dict:
    tenant = await _tenant(tenant_id)
    return j(await compare_search(tenant, body))


# ---------------------------------------------------------------- feedback

class Interaction(BaseModel):
    clicked: bool = False
    viewed: bool = False
    viewDurationSeconds: int = Field(default=0, ge=0, le=86_400)
    position: int | None = Field(default=None, ge=1, le=1000)


class FeedbackIn(BaseModel):
    tenantId: str = Field(max_length=64)
    requestId: str = Field(max_length=100)
    recordId: str = Field(max_length=200)
    userId: str = Field(max_length=100)
    feedbackType: Literal["selection", "rating", "dismiss", "click", "view"]
    successScore: float | None = Field(default=None, ge=0, le=1)
    userRating: float | None = Field(default=None, ge=1, le=5)
    requestFeatures: dict = Field(default_factory=dict)
    candidateFeatures: dict = Field(default_factory=dict)
    attributeScores: dict = Field(default_factory=dict)
    interaction: Interaction = Field(default_factory=Interaction)
    embeddingSimilarity: float | None = Field(default=None, ge=-1, le=1)


@router.post("/feedback", status_code=201)
async def feedback(body: FeedbackIn) -> dict:
    await _tenant(body.tenantId)
    doc = body.model_dump()
    _safe_keys(doc)
    doc["createdAt"] = datetime.now(UTC)
    db = await mongo.db()
    res = await db["feedback_events"].insert_one(doc)
    return {"feedbackId": str(res.inserted_id)}


@router.get("/feedback")
async def list_feedback(tenantId: str | None = None, limit: int = 50) -> list[dict]:
    db = await mongo.db()
    q = {"tenantId": tenantId} if tenantId else {}
    return j(await db["feedback_events"].find(q).sort("createdAt", -1).limit(max(1, min(limit, 200))).to_list(None))


# ---------------------------------------------------------------- audits

@router.get("/audits")
async def list_audits(tenantId: str | None = None, limit: int = 50) -> dict:
    db = await mongo.db()
    q = {"tenantId": tenantId} if tenantId else {}
    rows = await db["api_audits"].find(q, {"sanitizedRequest": 0, "apiResponse": 0, "semanticSearchResponse": 0, "modelSearchResponse": 0}) \
        .sort("createdAt", -1).limit(max(1, min(limit, 200))).to_list(None)
    oldest = await db["api_audits"].find_one(q, {"createdAt": 1}, sort=[("createdAt", 1)])
    total = await db["api_audits"].count_documents(q)
    return j({"total": total, "oldest": oldest and oldest["createdAt"], "items": rows})


@router.get("/audits/{request_id}")
async def get_audit(request_id: str) -> dict:
    db = await mongo.db()
    doc = await db["api_audits"].find_one({"requestId": request_id})
    if not doc:
        raise HTTPException(404, "Unknown requestId")
    fb = await db["feedback_events"].find({"requestId": request_id}).to_list(50)
    return j({"audit": doc, "feedback": fb})
