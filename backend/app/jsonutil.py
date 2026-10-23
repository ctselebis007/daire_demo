"""JSON helpers for Mongo documents."""

from __future__ import annotations

from typing import Any

from bson import ObjectId
from bson.binary import Binary
from fastapi.encoders import jsonable_encoder

_ENC = {ObjectId: str, Binary: lambda b: f"<binary {len(b)} bytes>"}


def j(value: Any) -> Any:
    return jsonable_encoder(value, custom_encoder=_ENC)
