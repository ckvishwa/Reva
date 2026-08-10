from pathlib import Path

from reva_core.config.settings import Settings, load_settings


def test_default_settings_are_safe_for_dev(monkeypatch):
    monkeypatch.delenv("REVA_LLM_PROVIDER_API_KEY", raising=False)
    settings = load_settings(_env_file=None)
    assert settings.environment == "dev"
    assert settings.api_host == "127.0.0.1"
    assert settings.log_level == "info"
    assert settings.llm_provider_api_key is None


def test_db_path_is_under_data_dir():
    settings = load_settings(_env_file=None, data_dir=Path("./somewhere"))
    assert settings.db_path == Path("somewhere/reva.db")


def test_secret_str_never_renders_in_repr():
    settings = Settings(_env_file=None, llm_provider_api_key="sk-real-secret")
    assert "sk-real-secret" not in repr(settings)
    assert "sk-real-secret" not in str(settings)


def test_load_settings_accepts_localhost_variants():
    for host in ["127.0.0.1", "localhost", "::1"]:
        settings = load_settings(_env_file=None, api_host=host)
        assert settings.api_host == host
