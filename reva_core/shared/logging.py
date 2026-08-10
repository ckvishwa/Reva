"""Structured JSON logging with mandatory secret redaction.

Every log line is a JSON object with: timestamp (UTC ISO-8601), level,
component, message, optional correlation_id, and optional safe metadata.
Any `extra={...}` key matching shared.redaction.SENSITIVE_KEYS is replaced
before it reaches the stream — callers cannot opt out of this.

Raw request bodies and raw microphone/audio data must never be passed as
`extra` metadata; this module has no way to distinguish a safe blob from
an unsafe one beyond key-name matching.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import IO, Any

from reva_core.shared.redaction import redact_mapping
from reva_core.shared.time import utc_now

_RESERVED_ATTRS = frozenset(vars(logging.LogRecord("", 0, "", 0, "", (), None)).keys()) | {
    "message",
    "asctime",
}


class RedactingJsonFormatter(logging.Formatter):
    """Formats records as single-line JSON, redacting sensitive extras."""

    def format(self, record: logging.LogRecord) -> str:
        extra = {k: v for k, v in record.__dict__.items() if k not in _RESERVED_ATTRS}
        safe_extra = redact_mapping(extra)

        payload: dict[str, Any] = {
            "timestamp": utc_now().isoformat(),
            "level": record.levelname,
            "component": record.name,
            "message": record.getMessage(),
        }
        correlation_id = safe_extra.pop("correlation_id", None)
        if correlation_id is not None:
            payload["correlation_id"] = correlation_id
        if safe_extra:
            payload["metadata"] = safe_extra
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "info", stream: IO[str] | None = None) -> logging.Logger:
    """Configure the `reva_core` logger tree. Idempotent: safe to call once at startup."""
    root = logging.getLogger("reva_core")
    root.setLevel(level.upper())
    handler = logging.StreamHandler(stream if stream is not None else sys.stdout)
    handler.setFormatter(RedactingJsonFormatter())
    root.handlers = [handler]
    root.propagate = False
    return root


def get_logger(component: str) -> logging.Logger:
    """Get a `reva_core.<component>` logger. Call `configure_logging` first."""
    return logging.getLogger(f"reva_core.{component}")
