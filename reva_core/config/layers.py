"""Configuration layers (AR-CORE-008): defaults < config file < environment < Credential Manager.

* **Defaults** are the field defaults in `Settings`.
* **Config file** `config.json` in the data directory: plain settings only (ports, models, paths,
  switches). It is easy to read and to back up, so it can never hold a secret: a file that names
  one is refused rather than used.
* **Environment** (`REVA_*` and `.env`) beats the file. Arguments passed in code beat both.
* **Secrets** come from Windows Credential Manager when a value is stored there, and only fall back
  to the environment when the vault has nothing (or no vault is available, as under pytest).

`resolve_secrets` never logs, prints or raises with a secret's value.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic.fields import FieldInfo
from pydantic_settings import PydanticBaseSettingsSource

from reva_core.security.credential_store import SecretStore, SecretStoreError
from reva_core.shared.errors import ConfigurationError

CONFIG_FILE_NAME = "config.json"
SECRET_FIELDS = frozenset({"llm_provider_api_key"})
_MAX_CONFIG_BYTES = 256 * 1024


def read_config_file(data_dir: Path, known_fields: frozenset[str]) -> dict[str, Any]:
    """The file layer. A missing file is an empty layer; a damaged or unsafe one is an error."""
    path = Path(data_dir) / CONFIG_FILE_NAME
    try:
        if not path.exists():
            return {}
        if path.stat().st_size > _MAX_CONFIG_BYTES:
            raise ConfigurationError("config.json is too large to be a settings file")
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigurationError("config.json could not be read as JSON") from exc
    if not isinstance(raw, dict):
        raise ConfigurationError("config.json must hold one JSON object")
    secrets_present = sorted(name for name in raw if name in SECRET_FIELDS)
    if secrets_present:
        raise ConfigurationError(
            f"config.json must not hold secrets ({', '.join(secrets_present)}); "
            "store them in Windows Credential Manager"
        )
    return {name: value for name, value in raw.items() if name in known_fields}


class ConfigFileSource(PydanticBaseSettingsSource):
    """Sits below the environment in `Settings.settings_customise_sources`."""

    def __init__(self, settings_cls: type[Any]) -> None:
        super().__init__(settings_cls)

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        return None, field_name, False  # unused: __call__ returns the whole layer

    def __call__(self) -> dict[str, Any]:
        state: Mapping[str, Any] = self.current_state
        data_dir = state.get("data_dir") or os.environ.get("REVA_DATA_DIR") or "./data"
        known = frozenset(self.settings_cls.model_fields)
        return read_config_file(Path(str(data_dir)), known)


def resolve_secrets(stores: Mapping[str, SecretStore] | None) -> dict[str, str]:
    """For each secret field, the Credential Manager value when there is one (it beats the env)."""
    resolved: dict[str, str] = {}
    for name, store in (stores or {}).items():
        if name not in SECRET_FIELDS:
            continue
        try:
            stored = store.read()
        except SecretStoreError:
            continue  # no vault: whatever the lower layers said stands
        if stored:
            resolved[name] = stored
    return resolved


__all__ = [
    "CONFIG_FILE_NAME",
    "SECRET_FIELDS",
    "ConfigFileSource",
    "read_config_file",
    "resolve_secrets",
]
