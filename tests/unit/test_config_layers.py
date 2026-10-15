"""B4: configuration precedence (AR-CORE-008): defaults < config.json < environment < vault."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reva_core.config.layers import read_config_file
from reva_core.config.settings import Settings, load_settings
from reva_core.security.credential_store import (
    InMemorySecretStore,
    SecretStoreError,
    UnavailableSecretStore,
)
from reva_core.shared.errors import ConfigurationError


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(__import__("os").environ):
        if name.startswith("REVA_") and name != "REVA_DATA_DIR":
            monkeypatch.delenv(name, raising=False)


def write_config(directory: Path, document: object) -> None:
    (directory / "config.json").write_text(json.dumps(document), encoding="utf-8")


def test_defaults_when_there_is_no_file(tmp_path: Path) -> None:
    settings = load_settings(_env_file=None, data_dir=tmp_path)

    assert settings.api_port == 8756 and settings.cloud_timeout_seconds == 8.0


def test_the_file_beats_the_defaults(tmp_path: Path) -> None:
    write_config(
        tmp_path, {"api_port": 9001, "cloud_timeout_seconds": 3.5, "kokoro_voice": "af_nova"}
    )

    settings = load_settings(_env_file=None, data_dir=tmp_path)

    assert (settings.api_port, settings.cloud_timeout_seconds, settings.kokoro_voice) == (
        9001,
        3.5,
        "af_nova",
    )


def test_the_environment_beats_the_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_config(tmp_path, {"api_port": 9001, "kokoro_voice": "af_nova"})
    monkeypatch.setenv("REVA_API_PORT", "9002")

    settings = load_settings(_env_file=None, data_dir=tmp_path)

    assert settings.api_port == 9002  # env
    assert settings.kokoro_voice == "af_nova"  # file still supplies what env does not


def test_arguments_in_code_beat_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_config(tmp_path, {"api_port": 9001})
    monkeypatch.setenv("REVA_API_PORT", "9002")

    assert load_settings(_env_file=None, data_dir=tmp_path, api_port=9003).api_port == 9003


def test_the_data_directory_can_itself_come_from_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_config(tmp_path, {"api_port": 9010})
    monkeypatch.setenv("REVA_DATA_DIR", str(tmp_path))

    assert load_settings(_env_file=None).api_port == 9010


def test_the_vault_beats_the_environment_for_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REVA_LLM_PROVIDER_API_KEY", "from-env-0123456789")

    from_env = load_settings(_env_file=None, data_dir=tmp_path)
    from_vault = load_settings(
        {"llm_provider_api_key": InMemorySecretStore("from-vault-0123456789")},
        _env_file=None,
        data_dir=tmp_path,
    )

    assert from_env.llm_provider_api_key is not None
    assert from_env.llm_provider_api_key.get_secret_value() == "from-env-0123456789"
    assert from_vault.llm_provider_api_key is not None
    assert from_vault.llm_provider_api_key.get_secret_value() == "from-vault-0123456789"


@pytest.mark.parametrize("store", [InMemorySecretStore(None), UnavailableSecretStore()])
def test_an_empty_or_missing_vault_leaves_the_environment_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, store: object
) -> None:
    monkeypatch.setenv("REVA_LLM_PROVIDER_API_KEY", "from-env-0123456789")

    settings = load_settings({"llm_provider_api_key": store}, _env_file=None, data_dir=tmp_path)  # type: ignore[dict-item]

    assert settings.llm_provider_api_key is not None
    assert settings.llm_provider_api_key.get_secret_value() == "from-env-0123456789"


def test_a_secret_in_the_file_is_refused_not_used(tmp_path: Path) -> None:
    write_config(tmp_path, {"api_port": 9001, "llm_provider_api_key": "sk-ant-leaked-0123456789"})

    with pytest.raises(ConfigurationError, match="must not hold secrets") as caught:
        load_settings(_env_file=None, data_dir=tmp_path)

    assert "sk-ant-leaked" not in str(caught.value)


@pytest.mark.parametrize("text", ["{ not json", "[1, 2]", '"text"', "null", ""])
def test_a_damaged_file_is_a_clear_error_not_silent_defaults(tmp_path: Path, text: str) -> None:
    (tmp_path / "config.json").write_text(text, encoding="utf-8")

    with pytest.raises(ConfigurationError):
        load_settings(_env_file=None, data_dir=tmp_path)


def test_unknown_keys_in_the_file_are_ignored(tmp_path: Path) -> None:
    write_config(tmp_path, {"flux_capacitor": 1, "api_port": 9020})

    assert load_settings(_env_file=None, data_dir=tmp_path).api_port == 9020
    assert read_config_file(tmp_path, frozenset({"api_port"})) == {"api_port": 9020}


def test_a_file_cannot_turn_the_api_public(tmp_path: Path) -> None:
    write_config(tmp_path, {"api_host": "0.0.0.0"})

    with pytest.raises(ConfigurationError, match="loopback"):
        load_settings(_env_file=None, data_dir=tmp_path)


def test_a_huge_file_is_refused(tmp_path: Path) -> None:
    (tmp_path / "config.json").write_text('{"x": "' + "a" * 300_000 + '"}', encoding="utf-8")

    with pytest.raises(ConfigurationError, match="too large"):
        load_settings(_env_file=None, data_dir=tmp_path)


def test_the_secret_never_appears_in_the_settings_repr(tmp_path: Path) -> None:
    settings = load_settings(
        {"llm_provider_api_key": InMemorySecretStore("vault-secret-0123456789")},
        _env_file=None,
        data_dir=tmp_path,
    )

    assert "vault-secret" not in repr(settings) and "vault-secret" not in str(settings)


def test_the_secret_store_error_type_is_what_a_missing_vault_raises() -> None:
    with pytest.raises(SecretStoreError):
        UnavailableSecretStore().read()


def test_settings_class_still_loads_without_a_data_directory_file() -> None:
    assert Settings(_env_file=None).api_port > 0  # type: ignore[call-arg]
