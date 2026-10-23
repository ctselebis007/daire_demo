"""Recommendation pipeline: validate -> render -> embed -> $rankFusion -> Voyage rerank -> OpenAI explanations."""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import UTC, datetime

from . import llm, voyage
from .audit import DEFAULT_PII, audit_writer, scrub
from .db import mongo
from .filters import FilterError
from .search import MODES, resolve_exact, run_mode
from .settings import store
from .templating import render, validate


class QueryError(ValueError):
    pass


def _render_query(tenant: dict, query: dict) -> tuple[str, str]:
    qc = tenant["queryConfig"]
    errors = validate(qc["schema"], query)
    if errors:
        raise QueryError("; ".join(errors))
    text = render(qc["serializationTemplate"], query)
    keyword = render(qc.get("keywordTemplate") or qc["serializationTemplate"], query)
    return text, keyword


def _ms(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000, 1)


def _weights(body: dict) -> dict | None:
    """Optional per-request $rankFusion weights; None means use the tenant default."""
    w = body.get("weights")
    if w is None:
        return None
    if not isinstance(w, dict) or set(w) - {"vector", "text"}:
        raise QueryError("weights must be an object with 'vector' and/or 'text'")
    out = {}
    for k in ("vector", "text"):
        v = w.get(k, 0)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 10:
            raise QueryError(f"weights.{k} must be a number between 0 and 10")
        out[k] = float(v)
    if out["vector"] + out["text"] <= 0:
        raise QueryError("at least one weight must be greater than 0")
    return out


async def compare_search(tenant: dict, body: dict) -> dict:
    query = body.get("query") or {}
    filters = body.get("filters") or []
    modes = [m for m in body.get("modes", list(MODES)) if m in MODES] or list(MODES)
    limit = max(1, min(int(body.get("limit", 10)), 100))
    weights = _weights(body)
    text, keyword = _render_query(tenant, query)
    t0 = time.perf_counter()
    qvec = await voyage.embed_query(text)
    embed_ms = _ms(t0)
    exact = await resolve_exact(tenant, body.get("vectorMode", "auto"))
    db = await mongo.db()
    runs = await asyncio.gather(*(run_mode(db, tenant, m, qvec, keyword, filters, limit, exact, weights) for m in modes))
    return {
        "tenantId": tenant["_id"],
        "datasetVersion": tenant["activeDatasetVersion"],
        "queryText": text,
        "keywordText": keyword,
        "embedMs": embed_ms,
        "runs": {r["mode"]: r for r in runs},
    }


async def recommend(tenant: dict, body: dict, endpoint: str) -> dict:
    s = store.current
    request_id = str(body.get("requestId") or f"req-{uuid.uuid4().hex[:16]}")[:100]
    rp = tenant.get("recommendationPipeline", {})
    query = body.get("query") or {}
    filters = body.get("filters") or []
    top_k = max(1, min(int(body.get("topK") or rp.get("topK", 10)), 50))
    overfetch = int(rp.get("overfetchFactor", 3))
    timings: dict[str, float] = {}
    t_total = time.perf_counter()
    audit = {
        "_id": str(uuid.uuid4()),
        "requestId": request_id,
        "tenantId": tenant["_id"],
        "endpoint": endpoint,
        "httpMethod": "POST",
        "sanitizedRequest": scrub(body, DEFAULT_PII | set(tenant.get("piiFields", []))),
        "createdAt": datetime.now(UTC),
    }
    try:
        text, keyword = _render_query(tenant, query)
        weights = _weights(body)

        t0 = time.perf_counter()
        qvec = await voyage.embed_query(text)
        timings["embed"] = _ms(t0)

        exact = await resolve_exact(tenant, body.get("vectorMode", "auto"))
        db = await mongo.db()
        t0 = time.perf_counter()
        hybrid = await run_mode(db, tenant, "hybrid", qvec, keyword, filters, top_k * overfetch, exact, weights)
        timings["hybridSearch"] = _ms(t0)
        candidates = hybrid["results"]
        audit["semanticSearchResponse"] = {
            "exact": exact,
            "candidates": [{"recordId": c["recordId"], **c["scores"]} for c in candidates],
        }

        rr_cfg = rp.get("rerank", {})
        reranked = False
        use_rerank = body.get("rerank", True) and rr_cfg.get("provider", "voyage") == "voyage" and s.rerank_enabled
        if use_rerank and candidates:
            pool = candidates[: int(rr_cfg.get("topN", 30))]
            t0 = time.perf_counter()
            rr = await voyage.rerank(text, [c["embeddingText"] for c in pool], top_k=top_k)
            timings["rerank"] = _ms(t0)
            ordered = []
            for r in rr:
                c = pool[r["index"]]
                c["scores"]["rerank"] = round(r["relevance_score"], 4)
                c["scores"]["preRerankRank"] = c["rank"]
                ordered.append(c)
            candidates = ordered
            reranked = True
            audit["modelSearchResponse"] = {
                "reranker": s.rerank_model,
                "scores": [{"recordId": c["recordId"], "score": c["scores"]["rerank"]} for c in candidates],
            }
        final = candidates[:top_k]
        for i, c in enumerate(final, 1):
            c["rank"] = i

        exp_cfg = rp.get("explanations", {})
        explanation_error = None
        if body.get("explain", True) and exp_cfg.get("enabled", True) and s.openai_api_key and final:
            t0 = time.perf_counter()
            try:
                exps = await llm.explain(tenant.get("name", tenant["_id"]), text, final[: int(exp_cfg.get("maxResults", 10))])
                for c in final:
                    c["explanation"] = exps.get(c["recordId"])
            except Exception as exc:
                explanation_error = f"{exc.__class__.__name__}: {str(exc)[:200]}"
            timings["explain"] = _ms(t0)

        timings["total"] = _ms(t_total)
        response = {
            "requestId": request_id,
            "tenantId": tenant["_id"],
            "datasetVersion": tenant["activeDatasetVersion"],
            "queryText": text,
            "keywordText": keyword,
            "vectorSearch": "exact (ENN)" if exact else "ANN (HNSW)",
            "fusion": hybrid["fusion"],
            "weights": hybrid["weights"],
            "reranked": reranked,
            "reranker": s.rerank_model if reranked else None,
            "explanationError": explanation_error,
            "results": [{k: v for k, v in c.items() if k != "embeddingText"} for c in final],
            "timingsMs": timings,
            "pipeline": hybrid["pipeline"],
            "pipelineText": hybrid["pipelineText"],
            "mongosh": hybrid["mongosh"],
        }
        audit.update({
            "httpStatusCode": 200,
            "apiResponse": scrub({"results": [{"recordId": c["recordId"], "rank": c["rank"], "scores": c["scores"]} for c in final]}, DEFAULT_PII),
            "timingsMs": timings,
            "error": None,
        })
        return response
    except (QueryError, FilterError) as exc:
        audit.update({"httpStatusCode": 400, "error": {"code": "INVALID_QUERY", "message": str(exc)[:500]}})
        raise
    except Exception as exc:
        audit.update({"httpStatusCode": 500, "error": {"code": exc.__class__.__name__, "message": str(exc)[:500]}})
        raise
    finally:
        audit.setdefault("timingsMs", {**timings, "total": _ms(t_total)})
        audit_writer.enqueue(audit)
