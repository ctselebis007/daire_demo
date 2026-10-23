"""DB, Atlas Search and Vector Search index management (idempotent)."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

from pymongo import ASCENDING, DESCENDING
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import OperationFailure
from pymongo.operations import SearchIndexModel

from .db import ensure_collections

TEXT_INDEX = "dare_text"
VECTOR_INDEX = "dare_vector"

_PATH_RE = re.compile(r"^metadata(\.[A-Za-z0-9_]+)+$")
_SEARCH_TYPE = {"string": "token", "string[]": "token", "number": "number", "date": "date", "boolean": "boolean"}

DB_INDEXES: list[tuple[str, list[tuple[str, int]], dict[str, Any]]] = [
    ("documents", [("tenantId", 1), ("datasetVersion", 1), ("recordId", 1)], {"name": "uniq_tenant_version_record", "unique": True}),
    ("documents", [("tenantId", 1), ("datasetVersion", 1), ("embeddingHash", 1)], {"name": "tenant_version_embhash"}),
    ("documents", [("tenantId", 1), ("datasetVersion", 1), ("status", 1), ("updatedAt", -1)], {"name": "tenant_version_status_updated"}),
    ("tenants", [("clientId", 1)], {"name": "clientId"}),
    ("ingestion_jobs", [("status", 1), ("createdAt", 1)], {"name": "status_created"}),
    ("ingestion_jobs", [("tenantId", 1), ("createdAt", -1)], {"name": "tenant_created"}),
    ("ingestion_jobs", [("tenantId", 1), ("batchId", 1)], {"name": "uniq_tenant_batch", "unique": True}),
    ("ingestion_payloads", [("status", 1), ("createdAt", 1)], {"name": "status_created"}),
    ("ingestion_payloads", [("jobId", 1), ("sequence", 1)], {"name": "uniq_job_sequence", "unique": True}),
    ("feedback_events", [("tenantId", 1), ("createdAt", -1)], {"name": "tenant_created"}),
    ("feedback_events", [("requestId", 1)], {"name": "requestId"}),
    ("feedback_events", [("tenantId", 1), ("userId", 1), ("createdAt", -1)], {"name": "tenant_user_created"}),
    ("api_audits", [("requestId", 1)], {"name": "requestId"}),
    ("api_audits", [("tenantId", 1), ("createdAt", -1)], {"name": "tenant_created"}),
]


def _keys(spec: list[tuple[str, int]]) -> list[tuple[str, int]]:
    return [(k, ASCENDING if d == 1 else DESCENDING) for k, d in spec]


async def create_db_indexes(db: AsyncDatabase, ttl_days: int) -> list[dict]:
    await ensure_collections(db)
    results = []
    for coll, keys, opts in DB_INDEXES:
        results.append(await _create_one(db, coll, keys, opts))

    ttl_seconds = ttl_days * 86400
    ttl = {"name": "ttl_createdAt", "expireAfterSeconds": ttl_seconds}
    existing = await _existing_index(db, "api_audits", "ttl_createdAt")
    if existing and existing.get("expireAfterSeconds") != ttl_seconds:
        await db.command({"collMod": "api_audits", "index": {"name": "ttl_createdAt", "expireAfterSeconds": ttl_seconds}})
        results.append({"collection": "api_audits", "name": "ttl_createdAt", "result": "updated", "detail": f"TTL {ttl_days}d"})
    else:
        r = await _create_one(db, "api_audits", [("createdAt", 1)], ttl)
        r["detail"] = f"TTL {ttl_days}d"
        results.append(r)
    return results


async def _existing_index(db: AsyncDatabase, coll: str, name: str) -> dict | None:
    info = await db[coll].index_information()
    return info.get(name)


async def _create_one(db: AsyncDatabase, coll: str, keys, opts) -> dict:
    name = opts["name"]
    before = await _existing_index(db, coll, name)
    try:
        await db[coll].create_index(_keys(keys), **opts)
        return {"collection": coll, "name": name, "result": "unchanged" if before else "created"}
    except OperationFailure as exc:
        return {"collection": coll, "name": name, "result": "failed", "detail": str(exc.details.get("errmsg") if exc.details else exc)[:300]}


# ---------- Search index definition generator ----------

def collect_filter_fields(tenants: list[dict]) -> tuple[dict[str, str], list[str]]:
    """Union of tenant filter fields -> {path: type}. Conflicting types keep the first and warn."""
    fields: dict[str, str] = {}
    warnings: list[str] = []
    for t in sorted(tenants, key=lambda x: x["_id"]):
        for f in t.get("indexConfig", {}).get("filterFields", []):
            path, ftype = f.get("path", ""), f.get("type", "string")
            if not _PATH_RE.match(path) or ftype not in _SEARCH_TYPE:
                warnings.append(f"{t['_id']}: ignored invalid filter field {path!r} ({ftype})")
                continue
            if path in fields and fields[path] != ftype:
                warnings.append(f"{t['_id']}: {path} type {ftype} conflicts with {fields[path]}; keeping {fields[path]}")
                continue
            fields[path] = ftype
    return fields, warnings


def build_search_definition(tenants: list[dict]) -> tuple[dict, list[str]]:
    fields, warnings = collect_filter_fields(tenants)
    metadata: dict = {"type": "document", "fields": {}}
    for path, ftype in sorted(fields.items()):
        parts = path.split(".")[1:]
        node = metadata
        for p in parts[:-1]:
            node = node["fields"].setdefault(p, {"type": "document", "fields": {}})
        node["fields"][parts[-1]] = {"type": _SEARCH_TYPE[ftype]}
    definition = {
        "mappings": {
            "dynamic": False,
            "fields": {
                "tenantId": {"type": "token"},
                "datasetVersion": {"type": "number"},
                "status": {"type": "number"},
                "keywordText": {"type": "string", "analyzer": "lucene.english"},
                "metadata": metadata,
            },
        }
    }
    return definition, warnings


def build_vector_definition(tenants: list[dict], dims: int) -> tuple[dict, list[str]]:
    fields, warnings = collect_filter_fields(tenants)
    definition = {
        "fields": [
            {"type": "vector", "path": "embedding", "numDimensions": dims, "similarity": "dotProduct", "quantization": "scalar"},
            {"type": "filter", "path": "tenantId"},
            {"type": "filter", "path": "datasetVersion"},
            {"type": "filter", "path": "status"},
            *({"type": "filter", "path": p} for p in sorted(fields)),
        ]
    }
    return definition, warnings


def _hash(defn: dict) -> str:
    return hashlib.sha256(json.dumps(defn, sort_keys=True).encode()).hexdigest()


async def _desired(db: AsyncDatabase, kind: str, dims: int) -> tuple[str, str, dict, list[str]]:
    tenants = await db["tenants"].find({"status": "active"}, {"indexConfig": 1}).to_list(None)
    if kind == "search":
        d, w = build_search_definition(tenants)
        return TEXT_INDEX, "search", d, w
    d, w = build_vector_definition(tenants, dims)
    return VECTOR_INDEX, "vectorSearch", d, w


async def _list_search(db: AsyncDatabase) -> dict[str, dict]:
    cursor = await db["documents"].list_search_indexes()
    return {i["name"]: i for i in await cursor.to_list(None)}


async def create_or_update_search_index(db: AsyncDatabase, kind: str, dims: int) -> dict:
    await ensure_collections(db)
    name, itype, definition, warnings = await _desired(db, kind, dims)
    desired_hash = _hash(definition)
    existing = (await _list_search(db)).get(name)
    meta = await db["dare_meta"].find_one({"_id": f"index:{name}"})
    try:
        if existing is None:
            await db["documents"].create_search_index(SearchIndexModel(definition=definition, name=name, type=itype))
            result = "created"
        elif not meta or meta.get("hash") != desired_hash:
            if kind == "vector" and _dims_of(existing) not in (None, dims):
                # numDimensions can't change in place; drop and recreate.
                await db["documents"].drop_search_index(name)
                result = "recreate-pending"
            else:
                await db["documents"].update_search_index(name, definition)
                result = "updated"
        else:
            result = "unchanged"
    except OperationFailure as exc:
        return {"name": name, "type": itype, "result": "failed", "detail": str(exc)[:400], "warnings": warnings}
    if result != "recreate-pending":
        await db["dare_meta"].update_one(
            {"_id": f"index:{name}"},
            {"$set": {"hash": desired_hash, "definition": definition, "updatedAt": datetime.now(UTC)}},
            upsert=True,
        )
    return {"name": name, "type": itype, "result": result, "definition": definition, "warnings": warnings}


def _dims_of(index: dict) -> int | None:
    for f in (index.get("latestDefinition") or {}).get("fields", []):
        if f.get("type") == "vector":
            return f.get("numDimensions")
    return None


async def index_status(db: AsyncDatabase, dims: int) -> dict:
    await ensure_collections(db)
    db_idx = []
    for coll in ("documents", "tenants", "ingestion_jobs", "ingestion_payloads", "feedback_events", "api_audits"):
        for name, spec in (await db[coll].index_information()).items():
            db_idx.append({
                "collection": coll,
                "name": name,
                "keys": spec["key"],
                "unique": spec.get("unique", False),
                "expireAfterSeconds": spec.get("expireAfterSeconds"),
            })
    search = []
    try:
        listed = await _list_search(db)
    except OperationFailure as exc:
        return {"db": db_idx, "search": [], "error": str(exc)[:300]}
    for kind in ("search", "vector"):
        name, itype, definition, warnings = await _desired(db, kind, dims)
        meta = await db["dare_meta"].find_one({"_id": f"index:{name}"})
        current = listed.get(name)
        stale = current is not None and (not meta or meta.get("hash") != _hash(definition))
        search.append({
            "name": name,
            "type": itype,
            "exists": current is not None,
            "status": (current or {}).get("status", "MISSING"),
            "queryable": bool((current or {}).get("queryable")),
            "stale": stale,
            "warnings": warnings,
            "desiredDefinition": definition,
        })
    return {"db": db_idx, "search": search}
