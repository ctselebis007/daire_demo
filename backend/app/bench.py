"""Quick ANN-vs-ENN recall and latency benchmark per tenant (uses stored vectors as queries; no model calls)."""

from __future__ import annotations

import random
import statistics

from .db import mongo
from .ingestion import from_bson_vector
from .search import run_mode


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return round(s[min(len(s) - 1, int(round(p * (len(s) - 1))))], 1)


async def run_bench(tenant: dict, samples: int = 20, k: int = 10) -> dict:
    db = await mongo.db()
    samples = max(1, min(samples, 100))
    docs = await (await db["documents"].aggregate([
        {"$match": {"tenantId": tenant["_id"], "datasetVersion": tenant["activeDatasetVersion"], "status": 1}},
        {"$sample": {"size": samples}},
        {"$project": {"embedding": 1, "keywordText": 1}},
    ])).to_list(None)
    timings: dict[str, list[float]] = {"ann": [], "enn": [], "text": [], "hybrid": []}
    recalls: list[float] = []
    rng = random.Random(7)
    for d in docs:
        qvec = from_bson_vector(d["embedding"])
        words = d.get("keywordText", "").split()
        keyword = " ".join(rng.sample(words, k=min(6, len(words)))) if words else "consulting"
        ann = await run_mode(db, tenant, "vector", qvec, keyword, None, k, exact=False)
        enn = await run_mode(db, tenant, "vector", qvec, keyword, None, k, exact=True)
        txt = await run_mode(db, tenant, "text", qvec, keyword, None, k, exact=False)
        hyb = await run_mode(db, tenant, "hybrid", qvec, keyword, None, k, exact=False)
        a = {r["recordId"] for r in ann["results"]}
        e = {r["recordId"] for r in enn["results"]}
        recalls.append(len(a & e) / max(1, len(e)))
        timings["ann"].append(ann["timingMs"])
        timings["enn"].append(enn["timingMs"])
        timings["text"].append(txt["timingMs"])
        timings["hybrid"].append(hyb["timingMs"])
    count = await db["documents"].count_documents({"tenantId": tenant["_id"], "datasetVersion": tenant["activeDatasetVersion"]})
    return {
        "tenantId": tenant["_id"],
        "documents": count,
        "samples": len(docs),
        "k": k,
        "recallAtK": round(statistics.mean(recalls), 4) if recalls else None,
        "latencyMs": {m: {"p50": _pct(v, 0.5), "p95": _pct(v, 0.95), "mean": round(statistics.mean(v), 1) if v else 0} for m, v in timings.items()},
        "note": "Latencies are measured from the app (include network RTT to Atlas).",
    }
