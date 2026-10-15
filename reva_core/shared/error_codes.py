"""One typed error shape for every response (ARD-300 error taxonomy).

Every error body is `{"error": ..., "code": ..., "correlation_id": ...}`, plus `field`/`detail` for
domain validation. `error` is kept as it always was so existing callers keep working; `code` is the
stable taxonomy value apps switch on. Neither carries a stack trace, a path, a record's contents or
a secret.
"""

from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    CORE_INTERNAL = "CORE.INTERNAL"
    CORE_VALIDATION = "CORE.VALIDATION"
    CORE_NOT_FOUND = "CORE.NOT_FOUND"
    CORE_CONFLICT = "CORE.CONFLICT"
    CORE_UNAVAILABLE = "CORE.UNAVAILABLE"
    CORE_RATE_LIMITED = "CORE.RATE_LIMITED"
    CORE_UNSUPPORTED_VERSION = "CORE.UNSUPPORTED_VERSION"
    AUTH_REQUIRED = "AUTH.REQUIRED"
    AUTH_FORBIDDEN = "AUTH.FORBIDDEN"
    DOMAIN_VALIDATION = "DOMAIN.VALIDATION"
    DOMAIN_LOCKED = "DOMAIN.LOCKED"
    DOMAIN_MIGRATION_FAILED = "DOMAIN.MIGRATION_FAILED"
    DOMAIN_CONSENT_REQUIRED = "DOMAIN.CONSENT_REQUIRED"
    DOMAIN_NOT_FOUND = "DOMAIN.NOT_FOUND"
    DOMAIN_CONFLICT = "DOMAIN.CONFLICT"
    DOMAIN_DELETED = "DOMAIN.DELETED"
    DOMAIN_CORRUPT = "DOMAIN.CORRUPT"
    DOMAIN_UNAVAILABLE = "DOMAIN.UNAVAILABLE"
    ACTION_GRANT_MISMATCH = "ACTION.GRANT_MISMATCH"
    AVATAR_UNAVAILABLE = "AVATAR.UNAVAILABLE"


# The `error` strings the Core has always used -> their taxonomy code.
_BY_ERROR: dict[str, ErrorCode] = {
    "validation_error": ErrorCode.DOMAIN_VALIDATION,
    "domain_locked": ErrorCode.DOMAIN_LOCKED,
    "domain_wrong_key": ErrorCode.DOMAIN_LOCKED,
    "domain_migration_failed": ErrorCode.DOMAIN_MIGRATION_FAILED,
    "domain_corrupt": ErrorCode.DOMAIN_CORRUPT,
    "domain_kernel_unavailable": ErrorCode.DOMAIN_UNAVAILABLE,
    "sync_rejected": ErrorCode.DOMAIN_CONSENT_REQUIRED,
    "key_required": ErrorCode.DOMAIN_CONSENT_REQUIRED,
    "consent_required": ErrorCode.DOMAIN_CONSENT_REQUIRED,
    "conflict": ErrorCode.DOMAIN_CONFLICT,
    "deleted": ErrorCode.DOMAIN_DELETED,
    "not_found": ErrorCode.DOMAIN_NOT_FOUND,
    "unknown_domain": ErrorCode.DOMAIN_NOT_FOUND,
    "Unauthorized": ErrorCode.AUTH_REQUIRED,
    "gateway_unavailable": ErrorCode.CORE_UNAVAILABLE,
    "secret_store_unavailable": ErrorCode.CORE_UNAVAILABLE,
    "voice_unavailable": ErrorCode.CORE_UNAVAILABLE,
    "actions_unavailable": ErrorCode.CORE_UNAVAILABLE,
    "too_many_watchers": ErrorCode.CORE_RATE_LIMITED,
    "too_many_actions": ErrorCode.CORE_RATE_LIMITED,
    "too_many_sessions": ErrorCode.CORE_RATE_LIMITED,
    "session_not_found": ErrorCode.CORE_NOT_FOUND,
    "audio_not_found": ErrorCode.CORE_NOT_FOUND,
    "action_not_found": ErrorCode.CORE_NOT_FOUND,
    "invalid_key": ErrorCode.CORE_VALIDATION,
    "audio_too_large": ErrorCode.CORE_VALIDATION,
    "empty_audio": ErrorCode.CORE_VALIDATION,
    "unsupported_audio_type": ErrorCode.CORE_VALIDATION,
    "unsupported_schema_version": ErrorCode.CORE_UNSUPPORTED_VERSION,
    "grant_mismatch": ErrorCode.ACTION_GRANT_MISMATCH,
    "internal_error": ErrorCode.CORE_INTERNAL,
}

_BY_STATUS: dict[int, ErrorCode] = {
    400: ErrorCode.CORE_VALIDATION,
    401: ErrorCode.AUTH_REQUIRED,
    403: ErrorCode.AUTH_FORBIDDEN,
    404: ErrorCode.CORE_NOT_FOUND,
    405: ErrorCode.CORE_NOT_FOUND,
    409: ErrorCode.CORE_CONFLICT,
    413: ErrorCode.CORE_VALIDATION,
    415: ErrorCode.CORE_VALIDATION,
    422: ErrorCode.CORE_VALIDATION,
    423: ErrorCode.DOMAIN_LOCKED,
    429: ErrorCode.CORE_RATE_LIMITED,
    503: ErrorCode.CORE_UNAVAILABLE,
}


def code_for(error: str, status: int) -> ErrorCode:
    """The taxonomy code for an `error` string, falling back to the HTTP status, then INTERNAL."""
    known = _BY_ERROR.get(error)
    if known is not None:
        return known
    return _BY_STATUS.get(status, ErrorCode.CORE_INTERNAL)
