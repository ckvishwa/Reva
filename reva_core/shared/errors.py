"""REVA exception hierarchy.

Only these exception types exist. Do not add new ones without a real,
demonstrated need (see docs/architecture/module-boundaries.md).

Vendor/provider exceptions must never leak past `models/` — they are
normalized into `ProviderError` with an explicit `kind`.
"""

from __future__ import annotations

from enum import StrEnum


class RevaError(Exception):
    """Base class for all REVA domain errors."""


class ConfigurationError(RevaError):
    """Invalid or unsafe configuration (e.g. non-loopback API host)."""


class StorageError(RevaError):
    """SQLite lifecycle, migration, or repository failure."""


class ProviderErrorKind(StrEnum):
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    INVALID_RESPONSE = "invalid_response"
    AUTHENTICATION_FAILURE = "authentication_failure"
    RATE_LIMITED = "rate_limited"


class ProviderError(RevaError):
    """Normalized failure from any LLM/embedding/STT/TTS provider.

    Vendor SDKs raise their own exception types; provider adapters must
    catch those at the boundary and re-raise this instead, so orchestration
    never depends on a vendor's exception types.
    """

    def __init__(self, kind: ProviderErrorKind, message: str) -> None:
        super().__init__(message)
        self.kind = kind


class PolicyDeniedError(RevaError):
    """A requested action was denied by policy."""


class ValidationError(RevaError, ValueError):
    """A contract or input failed validation outside of Pydantic's own path.

    Pydantic's own `pydantic.ValidationError` is used for model construction
    failures; this type is for domain-level validation performed by hand
    (e.g. rejecting a naive datetime before it reaches a contract).

    Also inherits `ValueError` so that raising it from inside a Pydantic
    `AfterValidator` (e.g. `shared.time.ensure_utc`) gets wrapped into a
    proper `pydantic.ValidationError` by Pydantic's validator machinery,
    while direct callers outside Pydantic still see `RevaError`.
    """


class ToolExecutionError(RevaError):
    """A tool execution failed after policy approval."""


class SyncError(RevaError):
    """Synchronization failure (future: device sync)."""
