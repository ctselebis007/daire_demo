"""Allow-listed filter translation -> $vectorSearch MQL filter + Atlas Search compound clauses."""

from __future__ import annotations

from datetime import datetime
from typing import Any

OPS = {"eq", "ne", "in", "nin", "gt", "gte", "lt", "lte", "exists"}
MAX_LIST = 100
MAX_STR = 200


class FilterError(ValueError):
    pass


def _coerce_scalar(value: Any, ftype: str) -> Any:
    if isinstance(value, (dict, list)):
        raise FilterError("Filter values must be scalars")
    if ftype == "number":
        if isinstance(value, bool):
            raise FilterError("Expected a number")
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise FilterError(f"Expected a number, got {value!r}") from exc
    if ftype == "date":
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise FilterError(f"Expected an ISO date, got {value!r}") from exc
    if ftype == "boolean":
        if isinstance(value, bool):
            return value
        if str(value).lower() in ("true", "false"):
            return str(value).lower() == "true"
        raise FilterError(f"Expected a boolean, got {value!r}")
    s = str(value)
    if len(s) > MAX_STR:
        raise FilterError("String filter value too long")
    return s


def _coerce(value: Any, ftype: str, op: str) -> Any:
    if op == "exists":
        if not isinstance(value, bool):
            raise FilterError("exists expects true/false")
        return value
    if op in ("in", "nin"):
        if not isinstance(value, list) or not value or len(value) > MAX_LIST:
            raise FilterError(f"{op} expects a non-empty list (max {MAX_LIST})")
        return [_coerce_scalar(v, ftype) for v in value]
    return _coerce_scalar(value, ftype)


def translate(tenant: dict, filters: list[dict] | None) -> tuple[list[dict], list[dict], list[dict]]:
    """Returns (mql_clauses, search_filter_clauses, search_must_not_clauses)."""
    if not filters:
        return [], [], []
    allowed = {a["field"]: set(a.get("ops", [])) for a in tenant.get("filterConfig", {}).get("allowed", [])}
    types = {f["path"]: f.get("type", "string") for f in tenant.get("indexConfig", {}).get("filterFields", [])}
    mql: list[dict] = []
    s_filter: list[dict] = []
    s_not: list[dict] = []
    for f in filters:
        if not isinstance(f, dict):
            raise FilterError("Each filter must be an object")
        field, op, raw = f.get("field"), f.get("op"), f.get("value")
        if not isinstance(field, str) or not isinstance(op, str):
            raise FilterError("Filter requires string 'field' and 'op'")
        if field.startswith("$") or "$" in field:
            raise FilterError("Operator injection rejected")
        if op not in OPS:
            raise FilterError(f"Unsupported operator {op!r}")
        if field not in allowed or op not in allowed[field]:
            raise FilterError(f"Filter {field} {op} is not allowed for this tenant")
        if field not in types:
            raise FilterError(f"Filter field {field} is not indexed")
        ftype = types[field]
        v = _coerce(raw, ftype, op)

        if op == "eq":
            mql.append({field: v})
            s_filter.append({"equals": {"path": field, "value": v}})
        elif op == "ne":
            mql.append({field: {"$ne": v}})
            s_not.append({"equals": {"path": field, "value": v}})
        elif op == "in":
            mql.append({field: {"$in": v}})
            s_filter.append({"in": {"path": field, "value": v}})
        elif op == "nin":
            mql.append({field: {"$nin": v}})
            s_not.append({"in": {"path": field, "value": v}})
        elif op == "exists":
            mql.append({field: {"$exists": v}})
            (s_filter if v else s_not).append({"exists": {"path": field}})
        else:
            mql.append({field: {f"${op}": v}})
            s_filter.append({"range": {"path": field, op: v}})
    return mql, s_filter, s_not
