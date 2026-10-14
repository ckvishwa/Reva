"""Opens Kernel domain handles for the Core and maps Kernel errors to HTTP-friendly errors.

No domain rule lives here. The service only owns the handle lifecycle: open lazily on first
use (so a locked or missing vault never stops Core from starting), keep one handle per
domain, and close on shutdown.
"""

from __future__ import annotations

import threading
from pathlib import Path
from types import ModuleType
from typing import Any

from reva_core.domains.kernel_loader import KernelUnavailableError, load_kernel
from reva_core.domains.keys import DomainKeyProvider
from reva_core.shared.logging import get_logger

logger = get_logger("domains")

ENABLED_DOMAINS = ("finance",)

# Kernel error class name -> (stable code, HTTP status)
_ERROR_MAP: dict[str, tuple[str, int]] = {
    "Locked": ("domain_locked", 423),
    "WrongKey": ("domain_wrong_key", 423),
    "Corrupt": ("domain_corrupt", 500),
    "MigrationFailed": ("domain_migration_failed", 500),
    "Validation": ("validation_error", 422),
    "Conflict": ("conflict", 409),
    "NotFound": ("not_found", 404),
    "Deleted": ("deleted", 410),
    "Internal": ("internal_error", 500),
    "Rejected": ("sync_rejected", 403),
}


class DomainRequestError(Exception):
    """A Kernel failure expressed for the HTTP layer. Never carries record contents."""

    def __init__(self, code: str, status: int, detail: str = "", field: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.status = status
        self.detail = detail
        self.field = field


def translate(binding: ModuleType, exc: BaseException) -> DomainRequestError:
    """Map a Kernel `DomainError` subclass to a `DomainRequestError`."""
    name = type(exc).__name__
    code, status = _ERROR_MAP.get(name, ("internal_error", 500))
    if name == "Validation":
        return DomainRequestError(
            code, status, str(getattr(exc, "reason", "")), getattr(exc, "field", None)
        )
    if name in {"Conflict", "NotFound", "Deleted"}:
        return DomainRequestError(code, status, str(getattr(exc, "detail", "")))
    return DomainRequestError(code, status)


class DomainService:
    def __init__(
        self, data_dir: Path, key_provider: DomainKeyProvider, bindings: Path | None = None
    ) -> None:
        self._data_dir = Path(data_dir)
        self._keys = key_provider
        self._bindings = bindings
        self._lock = threading.Lock()
        self._handles: dict[str, Any] = {}
        self._module: ModuleType | None = None

    @property
    def enabled_domains(self) -> tuple[str, ...]:
        return ENABLED_DOMAINS

    def binding(self) -> ModuleType:
        if self._module is None:
            try:
                self._module = load_kernel(self._bindings)
            except KernelUnavailableError as exc:
                logger.error("domain kernel unavailable: %s", exc)
                raise DomainRequestError("domain_kernel_unavailable", 503) from exc
        return self._module

    def handle(self, domain: str) -> Any:
        if domain not in ENABLED_DOMAINS:
            raise DomainRequestError("not_found", 404, f"unknown domain {domain!r}")
        with self._lock:
            existing = self._handles.get(domain)
            if existing is not None:
                return existing
            module = self.binding()
            try:
                opened = module.open_domain(domain, self._keys, str(self._data_dir))
            except module.DomainError as exc:
                raise translate(module, exc) from exc
            self._handles[domain] = opened
            return opened

    def status(self, domain: str) -> dict[str, Any]:
        """Current state of a domain without raising: ready, or why it is not."""
        try:
            handle = self.handle(domain)
        except DomainRequestError as exc:
            return {"domain": domain, "enabled": True, "state": exc.code, "schema_version": None}
        return {
            "domain": domain,
            "enabled": True,
            "state": "ready",
            "schema_version": handle.schema_version(),
        }

    def close(self) -> None:
        with self._lock:
            handles, self._handles = self._handles, {}
        for handle in handles.values():
            close = getattr(handle, "close", None)
            if close is not None:
                close()
