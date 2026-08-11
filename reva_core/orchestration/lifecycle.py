"""Core lifecycle: the only orchestration Phase 0 needs.

Coordinates config -> storage bootstrap -> health, and clean shutdown.
Owns no SQL (delegates to `storage.bootstrap`) and no policy decisions.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from reva_core.agent.orchestrator import AssistantOrchestrator
from reva_core.config.settings import Settings
from reva_core.memory.embedding_backfill import backfill_missing_embeddings
from reva_core.memory.ranking import DEFAULT_HYBRID_RANKING_CONFIG, HybridRankingConfig
from reva_core.models.embedding import EmbeddingProvider
from reva_core.models.embedding_providers import OllamaEmbeddingProvider
from reva_core.security.local_token import ensure_local_token
from reva_core.shared.contracts.health import CoreStatus, HealthStatus
from reva_core.shared.errors import StorageError
from reva_core.shared.ids import new_id
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
        self._assistant_orchestrator: AssistantOrchestrator | None = None
        self._embedding_provider: EmbeddingProvider | None = None
        self._ranking_config: HybridRankingConfig = DEFAULT_HYBRID_RANKING_CONFIG

    def startup(self) -> HealthStatus:
        self._status = CoreStatus.STARTING
        self._conn, self._db_schema_version = initialize_database(self._settings.db_path)
        self._primary_device_id = DeviceRepository(self._conn).get_or_create_primary_device()
        self._local_token = ensure_local_token(self._settings.data_dir)
        self._embedding_provider = OllamaEmbeddingProvider(
            model=self._settings.embedding_model,
            api_base=self._settings.embedding_model_api_base,
            timeout_seconds=self._settings.embedding_timeout_seconds,
        )
        self._run_startup_backfill()
        if self._settings.assistant_orchestrator == "adk":
            # Imported lazily so `google.adk`/`litellm` are only ever
            # imported by a Core process that actually opted into ADK —
            # every other startup path (the "deterministic" default) never
            # touches this dependency at all.
            from reva_core.agent.adk_orchestrator import build_adk_orchestrator

            self._assistant_orchestrator = build_adk_orchestrator(
                conn=self._conn,
                origin_device_id=self._primary_device_id,
                model_name=self._settings.adk_model,
                model_api_base=self._settings.adk_model_api_base,
                timeout_seconds=self._settings.adk_timeout_seconds,
                embedding_provider=self._embedding_provider,
                embedding_model_id=self._settings.embedding_model,
                ranking_config=self._ranking_config,
            )
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

    def _run_startup_backfill(self) -> None:
        # asyncio.run is safe here: startup() runs before uvicorn creates
        # its own event loop. Any failure (Ollama unreachable, a single
        # record failing to embed) must never prevent Core from becoming
        # HEALTHY — this is a best-effort warm-up, not a startup
        # precondition. An empty memories table (the common CI case)
        # embeds zero records regardless of backend reachability.
        import asyncio

        assert self._embedding_provider is not None
        assert self._conn is not None
        try:
            result = asyncio.run(
                backfill_missing_embeddings(
                    self._conn,
                    self._embedding_provider,
                    model_id=self._settings.embedding_model,
                    correlation_id=new_id(),
                )
            )
            logger.info(
                "embedding backfill completed",
                extra={
                    "embedded_count": result.embedded_count,
                    "failed_count": result.failed_count,
                },
            )
        except Exception:
            logger.warning(
                "embedding backfill failed at startup; continuing without it", exc_info=True
            )

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

    @property
    def assistant_orchestrator(self) -> AssistantOrchestrator | None:
        """`None` is a valid, expected value — it means the
        "deterministic" default is active, not that startup() hasn't run.
        """
        return self._assistant_orchestrator

    @property
    def embedding_provider(self) -> EmbeddingProvider | None:
        return self._embedding_provider

    @property
    def embedding_model_id(self) -> str:
        return self._settings.embedding_model

    @property
    def ranking_config(self) -> HybridRankingConfig:
        return self._ranking_config
