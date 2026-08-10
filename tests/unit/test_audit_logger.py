import io
import json

from reva_core.audit.events import AuditEvent, AuditEventCategory, AuditOutcome
from reva_core.audit.logger import log_audit_event
from reva_core.shared.ids import new_id
from reva_core.shared.logging import configure_logging
from reva_core.shared.time import utc_now


def test_log_audit_event_emits_structured_log_line():
    stream = io.StringIO()
    configure_logging(level="info", stream=stream)

    event = AuditEvent(
        id=new_id(),
        category=AuditEventCategory.TOOL,
        action="open_url",
        outcome=AuditOutcome.SUCCESS,
        metadata={"url": "https://example.com"},
        occurred_at=utc_now(),
    )
    log_audit_event(event)

    payload = json.loads(stream.getvalue().strip().splitlines()[-1])
    assert payload["message"] == "open_url"
    assert payload["metadata"]["category"] == "tool"
    assert payload["metadata"]["outcome"] == "success"
    assert payload["metadata"]["url"] == "https://example.com"
