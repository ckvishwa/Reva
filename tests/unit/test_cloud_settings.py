import json

from reva_core.planner.cloud_settings import CloudReasoningSettings


def test_cloud_reasoning_is_off_by_default_and_discloses_text_only(tmp_path):
    settings = CloudReasoningSettings(tmp_path)
    assert settings.enabled is False
    assert settings.disclosure == {
        "text": "Final transcript and capability list (names and argument schemas)",
        "audio": "Never",
        "screens": "Never",
        "memory": "Never",
        "domain_data": "Never",
    }


def test_cloud_setting_persists_without_a_key(tmp_path):
    settings = CloudReasoningSettings(tmp_path)
    settings.set_enabled(True)
    assert CloudReasoningSettings(tmp_path).enabled is True
    assert json.loads((tmp_path / "cloud_reasoning.json").read_text()) == {"enabled": True}
