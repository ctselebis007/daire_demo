"""Setup settings: server-side only, masked when returned, persisted to .dare/settings.json (0600)."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from threading import Lock

from pydantic import BaseModel, Field, field_validator

DARE_HOME = Path(os.environ.get("DARE_HOME", Path(__file__).resolve().parents[2] / ".dare"))
SETTINGS_FILE = DARE_HOME / "settings.json"

SECRET_FIELDS = ("voyage_api_key", "openai_api_key")
ENV_OVERRIDES = {
    "mongodb_uri": "DARE_MONGODB_URI",
    "db_name": "DARE_DB_NAME",
    "voyage_api_key": "VOYAGE_API_KEY",
    "openai_api_key": "OPENAI_API_KEY",
}
EMBEDDING_MODELS = ("voyage-4-large", "voyage-4", "voyage-4-lite")
RERANK_MODELS = ("rerank-3", "rerank-3-lite", "disabled")
EMBEDDING_DIMENSIONS = (256, 512, 1024, 2048)

_URI_CREDS = re.compile(r"^(mongodb(?:\+srv)?://)([^:@/]+):([^@/]+)@")
_MASK = "••••"


class Settings(BaseModel):
    mongodb_uri: str = ""
    db_name: str = "dare"
    voyage_api_key: str = ""
    voyage_base_url: str = "https://ai.mongodb.com/v1"
    embedding_model: str = "voyage-4"
    embedding_dimensions: int = 1024
    rerank_model: str = "rerank-3-lite"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    audit_ttl_days: int = Field(default=90, ge=1, le=3650)
    purge_grace_seconds: int = Field(default=900, ge=0)

    @field_validator("mongodb_uri")
    @classmethod
    def _uri(cls, v: str) -> str:
        v = v.strip()
        if v and not (v.startswith("mongodb://") or v.startswith("mongodb+srv://")):
            raise ValueError("URI must start with mongodb:// or mongodb+srv://")
        return v

    @field_validator("db_name")
    @classmethod
    def _db(cls, v: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,63}", v):
            raise ValueError("Invalid database name")
        return v

    @field_validator("voyage_base_url")
    @classmethod
    def _base(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        if not v.startswith("https://"):
            raise ValueError("Voyage base URL must use https://")
        return v

    @field_validator("embedding_model")
    @classmethod
    def _emb(cls, v: str) -> str:
        if v not in EMBEDDING_MODELS:
            raise ValueError(f"embedding_model must be one of {EMBEDDING_MODELS}")
        return v

    @field_validator("embedding_dimensions")
    @classmethod
    def _dims(cls, v: int) -> int:
        if v not in EMBEDDING_DIMENSIONS:
            raise ValueError(f"embedding_dimensions must be one of {EMBEDDING_DIMENSIONS}")
        return v

    @field_validator("rerank_model")
    @classmethod
    def _rr(cls, v: str) -> str:
        if v not in RERANK_MODELS:
            raise ValueError(f"rerank_model must be one of {RERANK_MODELS}")
        return v

    @property
    def mongo_ready(self) -> bool:
        return bool(self.mongodb_uri and self.db_name)

    @property
    def rerank_enabled(self) -> bool:
        return self.rerank_model != "disabled" and bool(self.voyage_api_key)


def redact_uri(uri: str) -> str:
    return _URI_CREDS.sub(lambda m: f"{m.group(1)}{m.group(2)}:{_MASK}@", uri)


def mask_secret(value: str) -> str:
    if not value:
        return ""
    return f"{_MASK}{value[-4:]}" if len(value) > 8 else _MASK


class SettingsStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._settings = self._load()

    def _load(self) -> Settings:
        data: dict = {}
        if SETTINGS_FILE.exists():
            try:
                data = json.loads(SETTINGS_FILE.read_text())
            except (OSError, json.JSONDecodeError):
                data = {}
        for field, env in ENV_OVERRIDES.items():
            if os.environ.get(env):
                data[field] = os.environ[env]
        return Settings(**data)

    @property
    def current(self) -> Settings:
        return self._settings

    def update(self, patch: dict) -> Settings:
        with self._lock:
            merged = self._settings.model_dump()
            for key, value in patch.items():
                if key not in merged or value is None:
                    continue
                # Masked or blank secrets mean "keep the existing value".
                if key in SECRET_FIELDS and (value == "" or str(value).startswith(_MASK)):
                    continue
                if key == "mongodb_uri" and _MASK in str(value):
                    continue
                merged[key] = value
            new = Settings(**merged)
            self._persist(new)
            self._settings = new
            return new

    def _persist(self, s: Settings) -> None:
        DARE_HOME.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = SETTINGS_FILE.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump(s.model_dump(), fh, indent=2)
        os.replace(tmp, SETTINGS_FILE)
        os.chmod(SETTINGS_FILE, 0o600)

    def masked(self) -> dict:
        s = self._settings
        out = s.model_dump()
        out["mongodb_uri"] = redact_uri(s.mongodb_uri)
        for f in SECRET_FIELDS:
            out[f] = mask_secret(getattr(s, f))
        out["configured"] = {
            "mongodb": s.mongo_ready,
            "voyage": bool(s.voyage_api_key),
            "openai": bool(s.openai_api_key),
        }
        return out


store = SettingsStore()
