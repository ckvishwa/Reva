"""REVA Core configuration.

Loaded from environment variables (prefix `REVA_`) and an optional
`.env` file. Safe defaults only; no field is required to start REVA
in dev mode. Secrets use `SecretStr` so they never render in plain
text via `repr()`/`str()`, including in accidental log lines.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from reva_core.shared.errors import ConfigurationError

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


class Settings(BaseSettings):
    """Raw settings as loaded from environment/`.env`. Prefer `load_settings()`."""

    model_config = SettingsConfigDict(env_prefix="REVA_", env_file=".env", extra="ignore")

    environment: Literal["dev", "prod"] = "dev"
    api_host: str = "127.0.0.1"
    api_port: int = 8756
    data_dir: Path = Path("./data")
    log_level: Literal["debug", "info", "warning", "error"] = "info"

    # Where the generated Domain Kernel Python binding lives (`tools/kernel/build_bindings.py`).
    # `REVA_KERNEL_BINDINGS` overrides it. None = `kernel/bindings/python` in the checkout.
    kernel_bindings_dir: Path | None = None
    # Where Domain Kernel keys live. "windows" = Windows Credential Manager (the only choice
    # for real use). "memory" keeps keys in the Core process and loses them at exit: it exists
    # only so UI and end-to-end tests never create entries in the user's real vault, and it is
    # refused unless the data directory is inside the system temp directory.
    domain_keystore: Literal["windows", "memory"] = "windows"

    # Placeholder for a future real provider credential. Never a real key in
    # Phase 0 — no provider integration exists yet. Documented future path:
    # Windows Credential Manager / DPAPI, not plaintext `.env`, for prod.
    llm_provider_api_key: SecretStr | None = None

    # "deterministic" (default) preserves Phase 1A/1B's exact FakeLLMProvider
    # echo behavior - every existing test and the default `python -m
    # reva_core --serve` stay untouched. "adk" opts a running Core into
    # Slice 5's AdkAssistantOrchestrator; see
    # docs/adr/ADR-017-google-adk-orchestration-dependency.md.
    assistant_orchestrator: Literal["deterministic", "adk"] = "deterministic"
    # LiteLlm model string. Default targets a local Ollama model (no cloud
    # credential required) - see ADR-017 for why.
    adk_model: str = "ollama_chat/llama3.1:8b"
    adk_model_api_base: str = "http://127.0.0.1:11434"
    adk_timeout_seconds: float = 30.0

    # Local-first embedding backend for hybrid semantic memory retrieval
    # (Slice 6). Same Ollama server the "adk" orchestrator path already
    # requires — see reva_core/models/embedding_providers.py.
    embedding_model: str = "nomic-embed-text"
    embedding_model_api_base: str = "http://127.0.0.1:11434"
    # Deliberately short relative to `adk_timeout_seconds`/
    # `AdkAssistantOrchestrator._DEFAULT_TIMEOUT_SECONDS` (30.0): a query
    # embedding call is one step inside a single ADK turn's budget, not the
    # whole turn. `hybrid_search` already degrades to lexical-only on any
    # embedding failure (Global Constraint), but only if that failure
    # surfaces quickly — a *hung* (not merely refused) Ollama connection
    # must not be allowed to consume the entire turn budget before the
    # fallback ever gets a chance to run. A local Ollama embedding call
    # normally completes in well under a second; 5s still leaves ~25s of
    # headroom for the rest of the turn.
    embedding_timeout_seconds: float = 5.0

    # Slice 7 local voice. TTS is disabled by default so ordinary Core
    # health and typed chat never depend on a heavy voice runtime being
    # installed. Paths are operator-provided environment values, not
    # production defaults, because the REVI reference audio and dedicated
    # Chatterbox interpreter are local/private assets.
    tts_enabled: bool = False
    tts_python: Path | None = None
    tts_reference_wav: Path | None = None
    tts_model_id: str = "shankarpandala/chatterbox-telugu"
    tts_device: str = "cuda"
    tts_default_language: Literal["en", "te"] = "en"
    tts_ready_timeout_seconds: float = 60.0
    tts_synthesis_timeout_seconds: float = 120.0

    # Speech-to-text defaults are intentionally CPU-first for Slice 7 so
    # STT does not contend with Ollama/Chatterbox on a 4 GB GPU.
    stt_model: str = "Systran/faster-whisper-small"
    stt_device: str = "cpu"
    stt_compute_type: str = "int8"
    stt_timeout_seconds: float = 60.0
    stt_max_upload_bytes: int = 10 * 1024 * 1024
    stt_max_duration_seconds: float = 30.0

    @property
    def db_path(self) -> Path:
        return self.data_dir / "reva.db"


def load_settings(**overrides: object) -> Settings:
    """Build `Settings` and enforce security invariants that Pydantic
    field validation alone should not own (kept as domain-level checks
    so callers see `ConfigurationError`, not a bare `pydantic.ValidationError`).
    """
    settings = Settings(**overrides)  # type: ignore[arg-type]
    if settings.api_host.lower() not in _LOOPBACK_HOSTS:
        raise ConfigurationError(
            f"REVA_API_HOST must be a loopback address, got {settings.api_host!r}. "
            "REVA Core is never publicly exposed (security invariant #2)."
        )
    if settings.domain_keystore == "memory":
        from reva_core.domains.keys import KeyStoreError, ensure_memory_keystore_allowed

        try:
            ensure_memory_keystore_allowed(settings.data_dir)
        except KeyStoreError as exc:
            raise ConfigurationError(str(exc)) from exc
    return settings
