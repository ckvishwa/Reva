"""Core lifecycle: the only orchestration Phase 0 needs.

Coordinates config -> storage bootstrap -> health, and clean shutdown.
Owns no SQL (delegates to `storage.bootstrap`) and no policy decisions.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from reva_core.config.settings import Settings
from reva_core.security.local_token import ensure_local_token
from reva_core.shared.contracts.health import CoreStatus, HealthStatus
from reva_core.shared.errors import StorageError
from reva_core.shared.logging import get_logger
from reva_core.shared.time import utc_now
from reva_core.storage.bootstrap import initialize_database
from reva_core.storage.repositories.device_repository import DeviceRepository

logger = get_logger("orchestration")


class CoreLifecycle:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._conn: sqlite3.Connection | None = None
        self._db_schema_version: int | None = None
        self._started_at: datetime | None = None
        self._status = CoreStatus.STOPPED
        self._local_token: str | None = None
        self._primary_device_id: str | None = None

    def startup(self) -> HealthStatus:
        self._status = CoreStatus.STARTING
        self._conn, self._db_schema_version = initialize_database(self._settings.db_path)
        self._primary_device_id = DeviceRepository(self._conn).get_or_create_primary_device()
        self._local_token = ensure_local_token(self._settings.data_dir)
        self._started_at = utc_now()
        self._status = CoreStatus.HEALTHY
        logger.info(
            "core started",
            extra={
                "db_schema_version": self._db_schema_version,
                "environment": self._settings.environment,
            },
        )
        return self.health()

    def shutdown(self) -> None:
        self._status = CoreStatus.SHUTTING_DOWN
        if self._conn is not None:
            self._conn.close()
            self._conn = None
        self._status = CoreStatus.STOPPED
        logger.info("core stopped")

    def health(self) -> HealthStatus:
        return HealthStatus(
            status=self._status,
            db_schema_version=self._db_schema_version or 0,
            started_at=self._started_at,
        )

    @property
    def connection(self) -> sqlite3.Connection:
        if self._conn is None:
            raise StorageError("storage not initialized; call startup() first")
        return self._conn

    @property
    def local_token(self) -> str:
        if self._local_token is None:
            raise StorageError("local token not initialized; call startup() first")
        return self._local_token

    @property
    def primary_device_id(self) -> str:
        if self._primary_device_id is None:
            raise StorageError("primary device not initialized; call startup() first")
        return self._primary_device_id
