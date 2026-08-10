from reva_core.shared.redaction import REDACTED_PLACEHOLDER, is_sensitive_key, redact_mapping


def test_is_sensitive_key_matches_known_keys():
    for key in [
        "api_key",
        "access_token",
        "refresh_token",
        "authorization",
        "password",
        "secret",
        "pairing_token",
        "client_secret",
    ]:
        assert is_sensitive_key(key) is True


def test_is_sensitive_key_case_insensitive():
    assert is_sensitive_key("API_KEY") is True
    assert is_sensitive_key("Authorization") is True


def test_is_sensitive_key_false_for_safe_key():
    assert is_sensitive_key("conversation_id") is False


def test_redact_mapping_replaces_sensitive_values():
    data = {"api_key": "sk-real-secret-value", "user": "alice"}
    result = redact_mapping(data)
    assert result["api_key"] == REDACTED_PLACEHOLDER
    assert result["user"] == "alice"
    assert "sk-real-secret-value" not in str(result)


def test_redact_mapping_recurses_into_nested_dicts():
    data = {"metadata": {"password": "hunter2", "note": "ok"}}
    result = redact_mapping(data)
    assert result["metadata"]["password"] == REDACTED_PLACEHOLDER
    assert result["metadata"]["note"] == "ok"


def test_redact_mapping_does_not_mutate_input():
    data = {"secret": "value"}
    redact_mapping(data)
    assert data["secret"] == "value"
