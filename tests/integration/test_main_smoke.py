"""Startup/shutdown smoke tests for `python -m reva_core`."""

from reva_core.__main__ import main


def test_main_starts_up_and_shuts_down_cleanly(tmp_path, monkeypatch):
    monkeypatch.setenv("REVA_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("REVA_LLM_PROVIDER_API_KEY", raising=False)

    exit_code = main([])

    assert exit_code == 0
    assert (tmp_path / "reva.db").exists()


def test_main_returns_nonzero_on_invalid_config(monkeypatch, tmp_path):
    monkeypatch.setenv("REVA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("REVA_API_HOST", "0.0.0.0")

    exit_code = main([])

    assert exit_code == 1
