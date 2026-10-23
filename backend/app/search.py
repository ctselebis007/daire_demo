"""Hybrid search ($rankFusion over $vectorSearch + $search) with tenant pre-filtering."""

from __future__ import annotations

import asyncio
import copy
import json
import re
import time
from datetime import datetime
from typing import Any

from pymongo.asynchronous.database import AsyncDatabase

from .db import mongo
from .filters import translate
from .indexes import TEXT_INDEX, VECTOR_INDEX
from .ingestion import from_bson_vector
from .tenant_cache import tenant_cache

MODES = ("vector", "text", "hybrid")
_PROJECT = {"_id": 0, "recordId": 1, "metadata": 1, "embeddingText": 1, "embedding": 1}


def _base(tenant: dict) -> tuple[list[dict], list[dict]]:
    tid, ver = tenant["_id"], tenant["activeDatasetVersion"]
    mql = [{"tenantId": tid}, {"datasetVersion": ver}, {"status": 1}]
    search = [
        {"equals": {"path": "tenantId", "value": tid}},
        {"equals": {"path": "datasetVersion", "value": ver}},
        {"equals": {"path": "status", "value": 1}},
    ]
    return mql, search


async def resolve_exact(tenant: dict, vector_mode: str) -> bool:
    if vector_mode == "exact":
        return True
    if vector_mode == "ann":
        return False
    threshold = tenant.get("indexConfig", {}).get("vector", {}).get("exactSearchBelowDocs", 0)
    if not threshold:
        return False
    n = await tenant_cache.active_doc_count(tenant["_id"], tenant["activeDatasetVersion"])
    return n < threshold


def build_stages(tenant: dict, qvec: list[float], keyword: str, filters: list[dict] | None, limit: int, exact: bool) -> dict:
    mql, s_filter, s_not = translate(tenant, filters)
    base_mql, base_search = _base(tenant)
    vs: dict[str, Any] = {
        "index": VECTOR_INDEX,
        "path": "embedding",
        "queryVector": qvec,
        "limit": limit,
        "filter": {"$and": base_mql + mql},
    }
    if exact:
        vs["exact"] = True
    else:
        mult = tenant.get("indexConfig", {}).get("vector", {}).get("numCandidatesMultiplier", 15)
        vs["numCandidates"] = min(max(limit * mult, limit), 10_000)
    compound: dict[str, Any] = {
        "must": [{"text": {"query": keyword or " ", "path": "keywordText"}}],
        "filter": base_search + s_filter,
    }
    if s_not:
        compound["mustNot"] = s_not
    return {
        "vector": [{"$vectorSearch": vs}],
        "text": [{"$search": {"index": TEXT_INDEX, "compound": compound}}, {"$limit": limit}],
    }


def build_pipeline(mode: str, stages: dict, weights: dict, limit: int) -> list[dict]:
    if mode == "vector":
        return [*stages["vector"], {"$project": {**_PROJECT, "score": {"$meta": "vectorSearchScore"}}}]
    if mode == "text":
        return [*stages["text"], {"$project": {**_PROJECT, "score": {"$meta": "searchScore"}}}]
    return [
        {"$rankFusion": {
            "input": {"pipelines": {"vector": stages["vector"], "text": stages["text"]}},
            "combination": {"weights": {"vector": weights.get("vector", 0.7), "text": weights.get("text", 0.3)}},
            "scoreDetails": True,
        }},
        {"$limit": limit},
        {"$project": {**_PROJECT, "score": {"$meta": "score"}, "scoreDetails": {"$meta": "scoreDetails"}}},
    ]


def display_pipeline(pipeline: list[dict]) -> list[dict]:
    """Copy of the pipeline with query vectors abbreviated, for UI/audit."""
    p = copy.deepcopy(pipeline)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "queryVector" in node and isinstance(node["queryVector"], list):
                node["queryVector"] = f"<{len(node['queryVector'])} floats>"
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(p)
    return p


_DATE_TOKEN = re.compile(r'\{\s*"__dare_date__":\s*"([^"]+)"\s*\}')


def pipeline_to_text(pipeline: list[dict]) -> str:
    """Executable mongosh/Compass text: dates as ISODate(), query vectors kept inline on one line."""
    vectors: list[list[float]] = []

    def swap_vectors(node: Any) -> Any:
        if isinstance(node, dict):
            out = {}
            for k, v in node.items():
                if k == "queryVector" and isinstance(v, list):
                    vectors.append(v)
                    out[k] = f"__dare_vec_{len(vectors) - 1}__"
                else:
                    out[k] = swap_vectors(v)
            return out
        if isinstance(node, list):
            return [swap_vectors(v) for v in node]
        return node

    def default(o: Any) -> Any:
        if isinstance(o, datetime):
            return {"__dare_date__": o.isoformat()}
        raise TypeError(f"Unsupported type {type(o).__name__}")

    text = json.dumps(swap_vectors(pipeline), indent=2, default=default)
    text = _DATE_TOKEN.sub(r'ISODate("\1")', text)
    for i, vec in enumerate(vectors):
        text = text.replace(f'"__dare_vec_{i}__"', json.dumps(vec, separators=(",", ":")))
    return text


def _dot(a: list[float], b: list[float]) -> float:
    return float(sum(x * y for x, y in zip(a, b, strict=False)))


def _post(rows: list[dict], qvec: list[float], mode: str) -> list[dict]:
    out = []
    for i, r in enumerate(rows, 1):
        emb = from_bson_vector(r.pop("embedding", None))
        item = {
            "rank": i,
            "recordId": r["recordId"],
            "metadata": r.get("metadata", {}),
            "embeddingText": r.get("embeddingText", ""),
            "scores": {"score": r.get("score"), "semanticSimilarity": round(_dot(qvec, emb), 4) if emb else None},
        }
        if mode == "vector":
            item["scores"]["vectorRank"] = i
        elif mode == "text":
            item["scores"]["textRank"] = i
        details = (r.get("scoreDetails") or {}).get("details") or []
        for d in details:
            name = d.get("inputPipelineName")
            rank = d.get("rank")
            if name in ("vector", "text"):
                item["scores"][f"{name}Rank"] = rank if isinstance(rank, int) else None
        out.append(item)
    return out


def _app_rrf(vec_rows: list[dict], text_rows: list[dict], weights: dict, limit: int) -> list[dict]:
    """Fallback for clusters without $rankFusion (< 8.0): same RRF formula (k=60)."""
    scores: dict[str, float] = {}
    docs: dict[str, dict] = {}
    ranks: dict[str, dict] = {}
    for name, rows in (("vector", vec_rows), ("text", text_rows)):
        w = weights.get(name, 1.0)
        for rank, r in enumerate(rows, 1):
            rid = r["recordId"]
            scores[rid] = scores.get(rid, 0.0) + w / (60 + rank)
            docs.setdefault(rid, r)
            ranks.setdefault(rid, {})[name] = rank
    ordered = sorted(scores, key=scores.get, reverse=True)[:limit]
    out = []
    for rid in ordered:
        d = dict(docs[rid])
        d["score"] = scores[rid]
        d["scoreDetails"] = {"details": [{"inputPipelineName": n, "rank": rk} for n, rk in ranks[rid].items()]}
        out.append(d)
    return out


async def run_mode(
    db: AsyncDatabase, tenant: dict, mode: str, qvec: list[float], keyword: str,
    filters: list[dict] | None, limit: int, exact: bool, weights: dict | None = None,
) -> dict:
    stages = build_stages(tenant, qvec, keyword, filters, limit, exact)
    weights = weights or tenant.get("recommendationPipeline", {}).get("fusion", {}).get("weights", {"vector": 0.7, "text": 0.3})
    t0 = time.perf_counter()
    native = mode != "hybrid" or mongo.capabilities.get("rankFusion", True)
    if native:
        pipeline = build_pipeline(mode, stages, weights, limit)
        rows = await (await db["documents"].aggregate(pipeline)).to_list(None)
        pipeline_text = pipeline_to_text(pipeline)
        shell = f"use {db.name}\n\ndb.getCollection(\"documents\").aggregate({pipeline_text})"
    else:
        vp = build_pipeline("vector", stages, weights, limit)
        tp = build_pipeline("text", stages, weights, limit)
        vrows, trows = await asyncio.gather(
            (await db["documents"].aggregate(vp)).to_list(None),
            (await db["documents"].aggregate(tp)).to_list(None),
        )
        rows = _app_rrf(vrows, trows, weights, limit)
        pipeline = [{"$comment": "app-side RRF fallback"}, *vp, *tp]
        pipeline_text = pipeline_to_text(vp)
        shell = (
            f"use {db.name}\n\n// app-side RRF fallback: two aggregations fused in the application\n"
            f"db.getCollection(\"documents\").aggregate({pipeline_text})\n\n"
            f"db.getCollection(\"documents\").aggregate({pipeline_to_text(tp)})"
        )
    ms = round((time.perf_counter() - t0) * 1000, 1)
    return {
        "mode": mode,
        "exact": exact,
        "fusion": "native $rankFusion" if (mode == "hybrid" and native) else ("app RRF" if mode == "hybrid" else None),
        "weights": weights if mode == "hybrid" else None,
        "results": _post(rows, qvec, mode),
        "timingMs": ms,
        "pipeline": display_pipeline(pipeline),
        "pipelineText": pipeline_text,
        "mongosh": shell,
    }
