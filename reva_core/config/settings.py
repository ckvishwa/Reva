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

    # Placeholder for a future real provider credential. Never a real key in
    # Phase 0 — no provider integration exists yet. Documented future path:
    # Windows Credential Manager / DPAPI, not plaintext `.env`, for prod.
    llm_provider_api_key: SecretStr | None = None

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
    return settings
