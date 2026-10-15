"""A small, strict JSON Schema subset for capability arguments (AR-AGT-002).

Only the keywords the capability registry uses are supported. Anything else in a schema is a
configuration error at load time (`UnsupportedSchema`), never silently ignored, so a registry edit
that relies on a keyword this validator does not enforce cannot slip through. Validation is pure:
no I/O, no model, deterministic.

Supported: `type` (object, string, number, integer, boolean, array of those), `properties`,
`required`, `additionalProperties` (false only), `enum`, `maxLength`, `minLength`, `pattern`,
`minimum`, `maximum`, `format` (date-time is checked as an ISO 8601 string; others are ignored
because they only annotate).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

_SUPPORTED = frozenset(
    {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "enum",
        "maxLength",
        "minLength",
        "pattern",
        "minimum",
        "maximum",
        "format",
    }
)
_MAX_DEPTH = 8


class UnsupportedSchema(ValueError):
    """The schema uses a keyword this validator does not enforce."""


def check_supported(schema: Any, path: str = "$") -> None:
    if not isinstance(schema, dict):
        raise UnsupportedSchema(f"{path}: a schema must be an object")
    for key, value in schema.items():
        if key not in _SUPPORTED:
            raise UnsupportedSchema(f"{path}: keyword {key!r} is not supported")
        if key == "properties":
            if not isinstance(value, dict):
                raise UnsupportedSchema(f"{path}.properties must be an object")
            for name, sub in value.items():
                check_supported(sub, f"{path}.properties.{name}")
        if key == "additionalProperties" and value is not False:
            raise UnsupportedSchema(f"{path}: only additionalProperties: false is supported")


def validate(value: Any, schema: dict[str, Any], path: str = "$", depth: int = 0) -> list[str]:
    """Problems found, as short path-qualified sentences. Empty means valid."""
    if depth > _MAX_DEPTH:
        return [f"{path}: nested too deeply"]
    problems: list[str] = []
    expected = schema.get("type")
    if expected is not None and not _type_ok(value, expected):
        return [f"{path}: expected {expected}"]
    if "enum" in schema and value not in schema["enum"]:
        problems.append(f"{path}: not one of the allowed values")
    if isinstance(value, str):
        problems += _string_problems(value, schema, path)
    elif _is_number(value):
        if "minimum" in schema and value < schema["minimum"]:
            problems.append(f"{path}: below the minimum")
        if "maximum" in schema and value > schema["maximum"]:
            problems.append(f"{path}: above the maximum")
    if isinstance(value, dict) and (schema.get("type") == "object" or "properties" in schema):
        properties: dict[str, Any] = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in value:
                problems.append(f"{path}.{name}: required")
        for name, item in value.items():
            if name in properties:
                problems += validate(item, properties[name], f"{path}.{name}", depth + 1)
            elif schema.get("additionalProperties") is False:
                problems.append(f"{path}.{name}: not allowed")
    return problems


def _string_problems(value: str, schema: dict[str, Any], path: str) -> list[str]:
    problems = []
    if "maxLength" in schema and len(value) > schema["maxLength"]:
        problems.append(f"{path}: too long")
    if "minLength" in schema and len(value) < schema["minLength"]:
        problems.append(f"{path}: too short")
    if "pattern" in schema and re.search(schema["pattern"], value) is None:
        problems.append(f"{path}: wrong format")
    if schema.get("format") == "date-time":
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            problems.append(f"{path}: not a date and time")
    return problems


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _type_ok(value: Any, expected: Any) -> bool:
    options = expected if isinstance(expected, list) else [expected]
    return any(_one_type_ok(value, option) for option in options)


def _one_type_ok(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "string":
        return isinstance(value, str)
    if expected == "number":
        return _is_number(value) and value == value and abs(value) != float("inf")
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    return False
