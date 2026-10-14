"""Opens Kernel domain handles for the Core and maps Kernel errors to HTTP-friendly errors.

No domain rule lives here. The service only owns the handle lifecycle: open lazily on first
use (so a locked or missing vault never stops Core from starting), keep one handle per
domain, and close on shutdown.

It also keeps a change counter per domain (SYNC-1e). The counter is bumped on every local commit
and every applied sync batch, and a screen waits on it (`wait_for_change`) instead of polling
or reloading only when it is opened. The counter holds no data.
"""

from __future__ import annotations

import asyncio
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


# Most long-polls that may wait at once. A person has a handful of screens open, not hundreds.
DEFAULT_MAX_WATCHERS = 8


class DomainService:
    def __init__(
        self,
        data_dir: Path,
        key_provider: DomainKeyProvider,
        bindings: Path | None = None,
        max_watchers: int = DEFAULT_MAX_WATCHERS,
    ) -> None:
        self._data_dir = Path(data_dir)
        self._keys = key_provider
        self._bindings = bindings
        self._lock = threading.Lock()
        self._handles: dict[str, Any] = {}
        self._module: ModuleType | None = None
        self._counters: dict[str, int] = dict.fromkeys(ENABLED_DOMAINS, 0)
        self._max_watchers = max_watchers
        self._waiters: list[tuple[str, asyncio.AbstractEventLoop, asyncio.Future[None]]] = []

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

    # ------------------------------------------------------------------ change counter

    def change_counter(self, domain: str) -> int:
        with self._lock:
            return self._counter_locked(domain)

    def note_change(self, domain: str) -> int:
        """Record that `domain` changed (a local commit or an applied sync batch). Thread-safe."""
        with self._lock:
            self._counter_locked(domain)
            self._counters[domain] += 1
            counter = self._counters[domain]
            woken = [w for w in self._waiters if w[0] == domain]
            self._waiters = [w for w in self._waiters if w[0] != domain]
        for _, loop, future in woken:
            try:
                loop.call_soon_threadsafe(_resolve, future)
            except RuntimeError:  # that waiter's loop is already closed
                continue
        return counter

    async def wait_for_change(self, domain: str, since: int | None, timeout: float) -> int:
        """The counter once it differs from `since`, or after `timeout` seconds unchanged.

        `since=None` means no baseline: the current counter is returned at once. A counter that
        is *lower* than `since` also counts as a change: Core restarted and the caller's baseline
        is from the previous run.
        """
        loop = asyncio.get_running_loop()
        future: asyncio.Future[None] = loop.create_future()
        with self._lock:
            counter = self._counter_locked(domain)
            if since is None or counter != since:
                return counter
            if len(self._waiters) >= self._max_watchers:
                raise DomainRequestError("too_many_watchers", 429, "too many open watchers")
            entry = (domain, loop, future)
            self._waiters.append(entry)
        try:
            await asyncio.wait_for(future, timeout=timeout)
        except TimeoutError:
            pass
        finally:
            with self._lock:
                if entry in self._waiters:
                    self._waiters.remove(entry)
        return self.change_counter(domain)

    def _counter_locked(self, domain: str) -> int:
        if domain not in self._counters:
            raise DomainRequestError("not_found", 404, f"unknown domain {domain!r}")
        return self._counters[domain]

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


def _resolve(future: asyncio.Future[None]) -> None:
    if not future.done():
        future.set_result(None)
