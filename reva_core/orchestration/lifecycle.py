"""Core lifecycle: the only orchestration Phase 0 needs.

Coordinates config -> storage bootstrap -> health, and clean shutdown.
Owns no SQL (delegates to `storage.bootstrap`) and no policy decisions.
"""

from __future__ import annotations

import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

from reva_core.agent.orchestrator import AssistantOrchestrator
from reva_core.config.settings import Settings
from reva_core.domains.keys import DomainKeyProvider, KeyStoreError, default_key_provider
from reva_core.domains.privacy import DomainPrivacyStore
from reva_core.domains.service import DomainService
from reva_core.domains.voice_expense import FinanceExpenseExecutor
from reva_core.gateway.manager import GatewayManager
from reva_core.memory.embedding_backfill import backfill_missing_embeddings
from reva_core.memory.ranking import DEFAULT_HYBRID_RANKING_CONFIG, HybridRankingConfig
from reva_core.models.embedding import EmbeddingProvider
from reva_core.models.embedding_providers import OllamaEmbeddingProvider
from reva_core.models.faster_whisper_stt import FasterWhisperSTTProvider
from reva_core.models.stt import SpeechToTextProvider
from reva_core.models.tts import TextToSpeechProvider
from reva_core.policy.apps import AppCatalog
from reva_core.policy.broker import Broker
from reva_core.policy.grants import grant_key_provider, load_or_create_signer
from reva_core.policy.ledger import SqliteLedger
from reva_core.providers.cloud import KEY_ENTRY, CloudReasoner, CloudSettingsStore
from reva_core.providers.registry import ProviderKind
from reva_core.providers.tts import RegistryTTS, build_tts_registry
from reva_core.security.credential_store import SecretStore, default_secret_store
from reva_core.security.local_token import ensure_local_token
from reva_core.shared.contracts.health import CoreStatus, HealthStatus
from reva_core.shared.errors import StorageError
from reva_core.shared.ids import new_id
from reva_core.shared.logging import get_logger
from reva_core.shared.time import utc_now
from reva_core.storage.bootstrap import initialize_database
from reva_core.storage.repositories.device_repository import DeviceRepository
from reva_core.voice.vocabulary import build_vocabulary_prompt

logger = get_logger("orchestration")


class CoreLifecycle:
    def __init__(
        self,
        settings: Settings,
        text_to_speech_provider: TextToSpeechProvider | None = None,
        speech_to_text_provider: SpeechToTextProvider | None = None,
        domain_key_provider: DomainKeyProvider | None = None,
        gateway_key_provider: DomainKeyProvider | None = None,
        anthropic_secret_store: SecretStore | None = None,
        grant_key_provider: DomainKeyProvider | None = None,
    ) -> None:
        self._settings = settings
        self._conn: sqlite3.Connection | None = None
        self._db_schema_version: int | None = None
        self._started_at: datetime | None = None
        self._status = CoreStatus.STOPPED
        self._local_token: str | None = None
        self._primary_device_id: str | None = None
        self._assistant_orchestrator: AssistantOrchestrator | None = None
        self._embedding_provider: EmbeddingProvider | None = None
        self._text_to_speech_provider = text_to_speech_provider
        self._speech_to_text_provider = speech_to_text_provider
        self._ranking_config: HybridRankingConfig = DEFAULT_HYBRID_RANKING_CONFIG
        self._domain_key_provider = domain_key_provider
        self._domain_service: DomainService | None = None
        self._domain_privacy = DomainPrivacyStore(settings.data_dir)
        self._gateway_key_provider = gateway_key_provider
        self._gateway: GatewayManager | None = None
        self._anthropic_secret_store = anthropic_secret_store
        self._grant_key_provider = grant_key_provider
        self._broker: Broker | None = None
        self._apps = AppCatalog(None)
        self._cloud_settings_store = CloudSettingsStore(settings.data_dir / "cloud_settings.json")

    def startup(self) -> HealthStatus:
        self._status = CoreStatus.STARTING
        self._conn, self._db_schema_version = initialize_database(self._settings.db_path)
        self._primary_device_id = DeviceRepository(self._conn).get_or_create_primary_device()
        self._local_token = ensure_local_token(self._settings.data_dir)
        # Domain files open lazily on first use, so a locked vault never blocks Core startup.
        self._domain_service = DomainService(
            self._settings.data_dir,
            self._domain_key_provider
            or default_key_provider(self._settings.domain_keystore, self._settings.data_dir),
            self._settings.kernel_bindings_dir,
        )
        # Off unless the user turned it on in Devices; a failure to listen never blocks Core.
        self._gateway = GatewayManager(
            self._settings,
            lambda: self.domain_service,
            self._domain_privacy,
            self._gateway_key_provider,
        )
        self._gateway.startup()
        self._embedding_provider = OllamaEmbeddingProvider(
            model=self._settings.embedding_model,
            api_base=self._settings.embedding_model_api_base,
            timeout_seconds=self._settings.embedding_timeout_seconds,
        )
        self._build_broker()
        self._build_speech_to_text_provider()
        self._build_text_to_speech_provider()
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

    def _build_broker(self) -> None:
        """The action broker. Without the OS key vault there is no way to sign a grant, so the
        broker stays off (the actions routes answer 503) and the rest of Core carries on."""
        assert self._conn is not None
        try:
            provider = self._grant_key_provider or grant_key_provider(
                self._settings.domain_keystore, self._settings.data_dir
            )
            signer = load_or_create_signer(provider)
            signer.write_public_key(self._settings.data_dir)
            self._apps = AppCatalog(self._settings.data_dir / "apps.json")
            self._broker = Broker(
                signer=signer,
                ledger=SqliteLedger(self._conn),
                app_keys=self._apps.allowed_keys,
                app_names=self._apps.display_names,
                core_executors={
                    "finance.add_transaction": FinanceExpenseExecutor(lambda: self.domain_service)
                },
            )
        except (KeyStoreError, OSError):
            logger.warning("action broker unavailable: the grant key could not be used")
            self._broker = None

    @property
    def broker(self) -> Broker | None:
        return self._broker

    @property
    def apps(self) -> AppCatalog:
        return self._apps

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

    def _build_text_to_speech_provider(self) -> None:
        if self._text_to_speech_provider is not None or not self._settings.tts_enabled:
            return
        output_dir = Path(tempfile.gettempdir()) / f"reva-tts-{new_id()}"
        registry = build_tts_registry(self._settings, output_dir)
        if not registry.names(ProviderKind.TTS):
            logger.warning("tts is enabled but no TTS provider is fully configured")
            return
        # Voice selection and manifest verification happen on first use, so a
        # large model never delays Core becoming healthy.
        self._text_to_speech_provider = RegistryTTS(registry, preferred=self._settings.tts_provider)

    def _build_speech_to_text_provider(self) -> None:
        if self._speech_to_text_provider is not None:
            return
        self._speech_to_text_provider = FasterWhisperSTTProvider(
            model=self._settings.stt_model,
            device=self._settings.stt_device,
            compute_type=self._settings.stt_compute_type,
            timeout_seconds=self._settings.stt_timeout_seconds,
            initial_prompt=build_vocabulary_prompt(self._settings.stt_vocabulary_extra),
        )

    def shutdown(self) -> None:
        self._status = CoreStatus.SHUTTING_DOWN
        self._shutdown_text_to_speech_provider()
        if self._gateway is not None:
            self._gateway.shutdown()
            self._gateway = None
        if self._domain_service is not None:
            self._domain_service.close()
            self._domain_service = None
        if self._conn is not None:
            self._conn.close()
            self._conn = None
        self._status = CoreStatus.STOPPED
        logger.info("core stopped")

    def _shutdown_text_to_speech_provider(self) -> None:
        provider = self._text_to_speech_provider
        shutdown = getattr(provider, "shutdown", None)
        if shutdown is None:
            return
        import asyncio

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(shutdown())
            return
        logger.warning("tts worker shutdown skipped because an event loop is already running")

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
    def domain_privacy(self) -> DomainPrivacyStore:
        return self._domain_privacy

    @property
    def gateway(self) -> GatewayManager:
        if self._gateway is None:
            raise RuntimeError("Core has not started")
        return self._gateway

    @property
    def domain_service(self) -> DomainService:
        if self._domain_service is None:
            raise RuntimeError("CoreLifecycle.startup() has not run")
        return self._domain_service

    @property
    def embedding_provider(self) -> EmbeddingProvider | None:
        return self._embedding_provider

    @property
    def embedding_model_id(self) -> str:
        return self._settings.embedding_model

    @property
    def ranking_config(self) -> HybridRankingConfig:
        return self._ranking_config

    @property
    def text_to_speech_provider(self) -> TextToSpeechProvider | None:
        return self._text_to_speech_provider

    @property
    def speech_to_text_provider(self) -> SpeechToTextProvider | None:
        return self._speech_to_text_provider

    @property
    def anthropic_secret_store(self) -> SecretStore:
        if self._anthropic_secret_store is None:
            self._anthropic_secret_store = default_secret_store(KEY_ENTRY)
        return self._anthropic_secret_store

    @property
    def cloud_settings_store(self) -> CloudSettingsStore:
        return self._cloud_settings_store

    def cloud_reasoner(self) -> CloudReasoner:
        return CloudReasoner(
            self._cloud_settings_store,
            self.anthropic_secret_store,
            model=self._settings.cloud_model,
            timeout_seconds=self._settings.cloud_timeout_seconds,
        )

    @property
    def settings(self) -> Settings:
        return self._settings
