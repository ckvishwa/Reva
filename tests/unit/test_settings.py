from pathlib import Path

from reva_core.config.settings import Settings, load_settings


def test_default_settings_are_safe_for_dev(monkeypatch):
    monkeypatch.delenv("REVA_LLM_PROVIDER_API_KEY", raising=False)
    settings = load_settings(_env_file=None)
    assert settings.environment == "dev"
    assert settings.api_host == "127.0.0.1"
    assert settings.log_level == "info"
    assert settings.assistant_orchestrator == "planner"
    assert not hasattr(settings, "llm_provider_api_key")


def test_db_path_is_under_data_dir():
    settings = load_settings(_env_file=None, data_dir=Path("./somewhere"))
    assert settings.db_path == Path("somewhere/reva.db")


def test_api_key_environment_variable_is_not_a_setting(monkeypatch):
    monkeypatch.setenv("REVA_LLM_PROVIDER_API_KEY", "sk-real-secret")
    settings = Settings(_env_file=None)
    assert "sk-real-secret" not in repr(settings)
    assert not hasattr(settings, "llm_provider_api_key")


def test_load_settings_accepts_localhost_variants():
    for host in ["127.0.0.1", "localhost", "::1"]:
        settings = load_settings(_env_file=None, api_host=host)
        assert settings.api_host == host
