"""DARE on MongoDB Atlas — FastAPI entrypoint."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pymongo.errors import PyMongoError, ServerSelectionTimeoutError

from . import voyage
from .audit import audit_writer
from .db import SetupIncomplete, mongo
from .filters import FilterError
from .ingestion import IngestError, worker
from .recommend import QueryError
from .routes_admin import router as admin_router
from .routes_v1 import router as v1_router
from .security import ADMIN_TOKEN, install_log_redaction
from .settings import redact_uri
from .templating import TemplateError
from .tenant_cache import tenant_cache
from .voyage import VoyageError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("dare")
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@asynccontextmanager
async def lifespan(_: FastAPI):
    install_log_redaction()
    audit_writer.start()
    worker.start()
    tenant_cache.start()
    port = os.environ.get("DARE_PORT", "8000")
    print(f"\n  DARE admin URL:  http://127.0.0.1:{port}/?token={ADMIN_TOKEN}"
          f"\n  Vite dev URL:    http://127.0.0.1:5173/?token={ADMIN_TOKEN}\n", flush=True)
    yield
    await tenant_cache.stop()
    await worker.stop()
    await audit_writer.stop()
    await voyage.close()
    await mongo.close()


app = FastAPI(title="DARE on MongoDB Atlas", version="0.1.0", lifespan=lifespan)
app.include_router(admin_router)
app.include_router(v1_router)


def _err(status: int, msg: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": redact_uri(msg)})


@app.exception_handler(SetupIncomplete)
async def _setup(_: Request, exc: SetupIncomplete):
    return _err(409, f"Setup incomplete: {exc}")


@app.exception_handler(IngestError)
@app.exception_handler(QueryError)
@app.exception_handler(FilterError)
@app.exception_handler(TemplateError)
async def _bad_request(_: Request, exc: Exception):
    return _err(400, str(exc))


@app.exception_handler(VoyageError)
async def _voyage(_: Request, exc: VoyageError):
    return _err(502, str(exc))


@app.exception_handler(ServerSelectionTimeoutError)
async def _mongo_down(_: Request, exc: ServerSelectionTimeoutError):
    return _err(503, "Cannot reach MongoDB (server selection timeout). Check URI, network access list, and DNS.")


@app.exception_handler(PyMongoError)
async def _mongo(_: Request, exc: PyMongoError):
    log.warning("MongoDB error: %s", exc)
    return _err(500, f"MongoDB error: {str(exc)[:400]}")


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}


if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        target = (FRONTEND_DIST / path).resolve()
        if path and target.is_file() and FRONTEND_DIST.resolve() in target.parents:
            return FileResponse(target)
        return FileResponse(FRONTEND_DIST / "index.html")
