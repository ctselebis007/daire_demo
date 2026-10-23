"""Sandboxed Jinja2 rendering and JSON Schema validation for tenant-supplied config."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache

from jinja2 import TemplateSyntaxError
from jinja2.sandbox import SandboxedEnvironment
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

_env = SandboxedEnvironment(autoescape=False, trim_blocks=True, lstrip_blocks=True)


class TemplateError(ValueError):
    pass


@lru_cache(maxsize=256)
def _compile(source: str):
    try:
        return _env.from_string(source)
    except TemplateSyntaxError as exc:
        raise TemplateError(f"Template syntax error: {exc}") from exc


def render(source: str, context: dict) -> str:
    try:
        text = _compile(source).render(**context)
    except TemplateError:
        raise
    except Exception as exc:
        raise TemplateError(f"Template render error: {exc.__class__.__name__}: {exc}") from exc
    return " ".join(text.split())


def check_template(source: str) -> None:
    _compile(source)


@lru_cache(maxsize=256)
def _validator(schema_json: str) -> Draft202012Validator:
    return Draft202012Validator(json.loads(schema_json))


def validator_for(schema: dict) -> Draft202012Validator:
    return _validator(json.dumps(schema, sort_keys=True))


def check_schema(schema: dict) -> None:
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ValueError(f"Invalid JSON Schema: {exc.message}") from exc


def validate(schema: dict, instance: dict) -> list[str]:
    errors = sorted(validator_for(schema).iter_errors(instance), key=lambda e: list(e.path))
    return [f"/{'/'.join(map(str, e.path))}: {e.message}"[:200] for e in errors[:10]]


def stable_hash(*parts: object) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(json.dumps(p, sort_keys=True, default=str).encode())
        h.update(b"\x1f")
    return "sha256:" + h.hexdigest()
