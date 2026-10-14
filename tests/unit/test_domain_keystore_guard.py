"""REVA_DOMAIN_KEYSTORE=memory must be impossible outside temp directories and in release builds."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

from reva_core.config.settings import ConfigurationError, load_settings
from reva_core.domains.keys import (
    InMemoryKeyProvider,
    KeyStoreError,
    default_key_provider,
    ensure_memory_keystore_allowed,
)


def _real_looking_dir() -> Path:
    # Never created or touched: only its location is judged.
    return Path.home() / "AppData" / "Local" / "Reva" / "data"


def test_memory_keystore_is_allowed_for_a_temp_data_dir(tmp_path: Path) -> None:
    ensure_memory_keystore_allowed(tmp_path)
    assert isinstance(default_key_provider("memory", tmp_path), InMemoryKeyProvider)
    settings = load_settings(data_dir=tmp_path, domain_keystore="memory")
    assert settings.domain_keystore == "memory"


def test_memory_keystore_is_refused_outside_the_temp_directory() -> None:
    with pytest.raises(KeyStoreError):
        ensure_memory_keystore_allowed(_real_looking_dir())
    with pytest.raises(KeyStoreError):
        default_key_provider("memory", _real_looking_dir())
    with pytest.raises(ConfigurationError):
        load_settings(data_dir=_real_looking_dir(), domain_keystore="memory")


def test_the_temp_directory_itself_is_not_a_data_directory() -> None:
    with pytest.raises(KeyStoreError):
        ensure_memory_keystore_allowed(Path(tempfile.gettempdir()))


def test_dot_dot_cannot_escape_the_temp_directory(tmp_path: Path) -> None:
    sneaky = tmp_path / ".." / ".." / ".." / ".." / "Users"
    with pytest.raises(KeyStoreError):
        ensure_memory_keystore_allowed(sneaky)


def test_memory_keystore_needs_the_data_dir_to_be_checked() -> None:
    with pytest.raises(KeyStoreError):
        default_key_provider("memory")


def test_memory_keystore_is_refused_in_a_frozen_release_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    with pytest.raises(KeyStoreError):
        ensure_memory_keystore_allowed(tmp_path)
    with pytest.raises(ConfigurationError):
        load_settings(data_dir=tmp_path, domain_keystore="memory")
    with pytest.raises(KeyStoreError):
        default_key_provider("memory", tmp_path)


def test_windows_keystore_default_never_reaches_the_real_vault_under_pytest() -> None:
    provider = default_key_provider("windows")
    with pytest.raises(KeyStoreError):
        provider.load_key("finance")
