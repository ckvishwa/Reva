import pytest
from pydantic import ValidationError as PydanticValidationError

from reva_core.audit.events import AuditEvent, AuditEventCategory, AuditOutcome
from reva_core.shared.ids import new_id
from reva_core.shared.time import utc_now


def _make_event(**overrides):
    defaults = dict(
        id=new_id(),
        category=AuditEventCategory.TOOL,
        action="open_url",
        outcome=AuditOutcome.SUCCESS,
        occurred_at=utc_now(),
    )
    defaults.update(overrides)
    return AuditEvent(**defaults)


def test_audit_event_accepts_safe_metadata():
    event = _make_event(metadata={"url": "https://example.com"})
    assert event.metadata["url"] == "https://example.com"


def test_audit_event_rejects_api_key_in_metadata():
    with pytest.raises(PydanticValidationError):
        _make_event(metadata={"api_key": "sk-secret"})


def test_audit_event_rejects_password_in_metadata():
    with pytest.raises(PydanticValidationError):
        _make_event(metadata={"password": "hunter2"})


def test_audit_event_defaults_to_empty_metadata():
    event = _make_event()
    assert event.metadata == {}
