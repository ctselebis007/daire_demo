"""Voyage AI client for the MongoDB-hosted endpoint (ai.mongodb.com/v1)."""

from __future__ import annotations

import asyncio
import random
from collections import OrderedDict

import httpx

from .settings import store

MAX_BATCH = 128
_RETRY_STATUS = {429, 500, 502, 503, 504}


class VoyageError(RuntimeError):
    pass


class _LRU:
    def __init__(self, size: int = 20_000) -> None:
        self.size = size
        self.data: OrderedDict[str, list[float]] = OrderedDict()

    def get(self, key: str) -> list[float] | None:
        v = self.data.get(key)
        if v is not None:
            self.data.move_to_end(key)
        return v

    def put(self, key: str, value: list[float]) -> None:
        self.data[key] = value
        self.data.move_to_end(key)
        while len(self.data) > self.size:
            self.data.popitem(last=False)


embedding_cache = _LRU()
_http: httpx.AsyncClient | None = None
_sem = asyncio.Semaphore(4)


def _client() -> httpx.AsyncClient:
    global _http
    if _http is None:
        _http = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))
    return _http


async def close() -> None:
    global _http
    if _http is not None:
        await _http.aclose()
        _http = None


async def _post(path: str, payload: dict) -> dict:
    s = store.current
    if not s.voyage_api_key:
        raise VoyageError("Voyage AI API key is not configured")
    url = f"{s.voyage_base_url}/{path}"
    headers = {"Authorization": f"Bearer {s.voyage_api_key}", "Content-Type": "application/json"}
    delay = 1.0
    for attempt in range(6):
        async with _sem:
            try:
                resp = await _client().post(url, json=payload, headers=headers)
            except httpx.TransportError as exc:
                if attempt == 5:
                    raise VoyageError(f"Voyage request failed: {exc.__class__.__name__}") from exc
                resp = None
        if resp is not None:
            if resp.status_code < 400:
                return resp.json()
            if resp.status_code not in _RETRY_STATUS or attempt == 5:
                raise VoyageError(f"Voyage {path} HTTP {resp.status_code}: {resp.text[:300]}")
        await asyncio.sleep(delay + random.random() * 0.5)
        delay = min(delay * 2, 20)
    raise VoyageError("Voyage request retries exhausted")


def _rows(body: dict) -> list[dict]:
    return body.get("data") or body.get("results") or []


async def embed(texts: list[str], input_type: str) -> tuple[list[list[float]], int]:
    """Embed texts in batches. Returns (vectors in input order, total tokens)."""
    s = store.current
    out: list[list[float] | None] = [None] * len(texts)
    tokens = 0

    async def run(start: int, chunk: list[str]) -> None:
        nonlocal tokens
        body = await _post("embeddings", {
            "input": chunk,
            "model": s.embedding_model,
            "input_type": input_type,
            "output_dimension": s.embedding_dimensions,
        })
        for row in _rows(body):
            out[start + row["index"]] = row["embedding"]
        tokens += (body.get("usage") or {}).get("total_tokens", 0)

    await asyncio.gather(*(run(i, texts[i:i + MAX_BATCH]) for i in range(0, len(texts), MAX_BATCH)))
    if any(v is None for v in out):
        raise VoyageError("Voyage returned fewer embeddings than requested")
    return out, tokens  # type: ignore[return-value]


async def embed_query(text: str) -> list[float]:
    vectors, _ = await embed([text], "query")
    return vectors[0]


async def rerank(query: str, documents: list[str], top_k: int | None = None) -> list[dict]:
    """Returns [{index, relevance_score}] sorted by relevance."""
    s = store.current
    payload: dict = {"query": query, "documents": documents, "model": s.rerank_model}
    if top_k:
        payload["top_k"] = top_k
    body = await _post("rerank", payload)
    return [{"index": r["index"], "relevance_score": r["relevance_score"]} for r in _rows(body)]
