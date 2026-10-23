"""Local admin token and log redaction."""

from __future__ import annotations

import hmac
import logging
import os
import re
import secrets

from fastapi import Header, HTTPException

from .settings import DARE_HOME

TOKEN_FILE = DARE_HOME / "admin_token"


def _load_or_create_token() -> str:
    if os.environ.get("DARE_ADMIN_TOKEN"):
        return os.environ["DARE_ADMIN_TOKEN"]
    DARE_HOME.mkdir(parents=True, exist_ok=True, mode=0o700)
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text().strip()
    token = secrets.token_urlsafe(24)
    fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(token)
    return token


ADMIN_TOKEN = _load_or_create_token()


def require_token(x_admin_token: str | None = Header(default=None)) -> None:
    supplied = x_admin_token or ""
    if not hmac.compare_digest(supplied.encode(), ADMIN_TOKEN.encode()):
        raise HTTPException(status_code=401, detail="Invalid or missing admin token")


class RedactingFilter(logging.Filter):
    _patterns = [
        (re.compile(r"(mongodb(?:\+srv)?://[^:@/\s]+:)[^@/\s]+@"), r"\1****@"),
        (re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+", re.I), r"\1****"),
        (re.compile(r"(sk-[A-Za-z0-9_\-]{4})[A-Za-z0-9_\-]+"), r"\1****"),
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for pat, repl in self._patterns:
            msg = pat.sub(repl, msg)
        record.msg, record.args = msg, None
        if "color_message" in record.__dict__:
            record.color_message = msg
        return True


def install_log_redaction() -> None:
    f = RedactingFilter()
    for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access", "httpx", "dare"):
        logging.getLogger(name).addFilter(f)
    for h in logging.getLogger().handlers:
        h.addFilter(f)
