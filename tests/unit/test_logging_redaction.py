import io
import json

from reva_core.shared.logging import configure_logging, get_logger


def _log_and_capture(**extra) -> dict:
    stream = io.StringIO()
    configure_logging(level="info", stream=stream)
    logger = get_logger("test")
    logger.info("test message", extra=extra)
    line = stream.getvalue().strip().splitlines()[-1]
    return json.loads(line)


def test_log_line_has_required_fields():
    payload = _log_and_capture()
    assert set(payload) >= {"timestamp", "level", "component", "message"}
    assert payload["level"] == "INFO"
    assert payload["component"] == "reva_core.test"
    assert payload["message"] == "test message"


def test_log_line_redacts_api_key():
    payload = _log_and_capture(api_key="sk-super-secret")
    serialized = json.dumps(payload)
    assert "sk-super-secret" not in serialized
    assert payload["metadata"]["api_key"] == "***REDACTED***"


def test_log_line_redacts_multiple_sensitive_keys():
    payload = _log_and_capture(password="hunter2", access_token="tok-abc")
    serialized = json.dumps(payload)
    assert "hunter2" not in serialized
    assert "tok-abc" not in serialized


def test_log_line_keeps_safe_metadata():
    payload = _log_and_capture(conversation_id="abc-123")
    assert payload["metadata"]["conversation_id"] == "abc-123"


def test_log_line_promotes_correlation_id():
    payload = _log_and_capture(correlation_id="corr-1")
    assert payload["correlation_id"] == "corr-1"
    assert "metadata" not in payload


def test_log_line_includes_exc_info_on_exception():
    stream = io.StringIO()
    configure_logging(level="info", stream=stream)
    logger = get_logger("test")
    try:
        raise ValueError("boom")
    except ValueError:
        logger.exception("something failed")
    payload = json.loads(stream.getvalue().strip().splitlines()[-1])
    assert "ValueError: boom" in payload["exc_info"]
