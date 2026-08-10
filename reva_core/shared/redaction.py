"""Single source of truth for which keys are secret.

Used by both structured logging (shared/logging.py) and audit events
(audit/events.py) so a key added to one is never missed by the other.
"""

from __future__ import annotations

from typing import Any

REDACTED_PLACEHOLDER = "***REDACTED***"

SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "api_key",
        "access_token",
        "refresh_token",
        "authorization",
        "password",
        "secret",
        "pairing_token",
        "client_secret",
    }
)


def is_sensitive_key(key: str) -> bool:
    return key.strip().lower() in SENSITIVE_KEYS


def redact_mapping(data: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy of `data` with sensitive values replaced.

    Recurses into nested dicts so a sensitive key buried in a metadata
    blob (e.g. audit event metadata) is still caught.
    """
    result: dict[str, Any] = {}
    for key, value in data.items():
        if is_sensitive_key(key):
            result[key] = REDACTED_PLACEHOLDER
        elif isinstance(value, dict):
            result[key] = redact_mapping(value)
        else:
            result[key] = value
    return result
