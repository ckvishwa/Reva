"""UTC time helpers. REVA never stores or accepts naive datetimes."""

from __future__ import annotations

from datetime import UTC, datetime

from reva_core.shared.errors import ValidationError


def utc_now() -> datetime:
    """Current time, timezone-aware, UTC."""
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """Reject naive datetimes; convert any aware datetime to UTC.

    Used as a Pydantic AfterValidator on every timestamp field in a
    durable or serialized contract.
    """
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValidationError(f"naive datetime not allowed: {value!r}")
    return value.astimezone(UTC)
