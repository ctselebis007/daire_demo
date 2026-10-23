# DARE on MongoDB Atlas (POC)

A multi-tenant AI recommendation platform built on MongoDB Atlas. Retrieval uses Atlas Vector Search and Atlas Search together with `$rankFusion`. Embeddings and reranking come from Voyage AI through `ai.mongodb.com`, and OpenAI writes the explanations.

## Prerequisites
- Python 3.12+ with [uv](https://docs.astral.sh/uv/)
- Node 20+
- An Atlas cluster running MongoDB 8.0 or later (9.0 targeted) on M10 or above. Add your IP to the cluster's network access list.
- A Voyage AI Model API key created in Atlas
- An OpenAI API key

## Run
```bash
cd dare-mdb
npm install        # installs concurrently (root)
npm run setup      # uv sync (backend) + npm install (frontend)
npm run dev        # backend :8000 (auto-reload) + Vite :5173 together
```
Open the **Vite dev URL** printed by the backend (`http://127.0.0.1:5173/?token=…`). The token is also stored in `.dare/admin_token`. Ctrl+C stops both.

Production-style alternative: `npm --prefix frontend run build`, then run only the backend; it serves the built UI on :8000.

## Demo flow
1. **Setup:** enter the MongoDB URI, DB name, Voyage key and OpenAI key, then **Save**. Run the three **Test** buttons.
2. **Admin:** run these in order:
   1. **Create DB Indexes**
   2. **Seed Synthetic Data** (3 tenants × 2,000 records)
   3. **Create Atlas Search Indexes**
   4. **Create Vector Search Indexes**

   Then wait for the status of both search indexes to reach `READY`.
3. **Playground:** pick a sample query, run **Compare search modes** (vector, text, `$rankFusion`), then run **Get recommendations** (Voyage rerank plus OpenAI explanations).
4. **Ingest:** generate sample records with seed 42 and submit them as `full_replace`. Embeddings are reused, the job waits until the search indexes have caught up, and then the active version pointer is switched atomically. You can roll back from **Tenants**.
5. **Feedback & Audit:** browse the PII-scrubbed audits. The TTL index removes seeded audits older than 90 days.
6. **Requirements:** see how the design answers each evaluation question, and run the benchmark comparing ANN and ENN recall plus latency by search mode.

## Security notes
- Secrets stay on the server in `.dare/settings.json` (file mode 0600, git-ignored) and are masked in the UI. Environment variables `DARE_MONGODB_URI`, `VOYAGE_API_KEY` and `OPENAI_API_KEY` take precedence over the file.
- Every API call requires the `X-Admin-Token` header, and the app binds to 127.0.0.1.
- Tenant templates render in a Jinja2 sandbox. Filters are checked against an allow-list and type-coerced, and `$`-prefixed keys are rejected.

## Tests
```bash
cd backend && uv run pytest -q
```
