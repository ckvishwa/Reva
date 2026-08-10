import uuid

from reva_core.api.correlation import resolve_correlation_id


def test_resolve_correlation_id_accepts_valid_uuid():
    given = str(uuid.uuid4())
    assert resolve_correlation_id(given) == given


def test_resolve_correlation_id_generates_when_none():
    generated = resolve_correlation_id(None)
    assert uuid.UUID(generated)


def test_resolve_correlation_id_generates_when_empty_string():
    generated = resolve_correlation_id("")
    assert uuid.UUID(generated)


def test_resolve_correlation_id_generates_when_malformed():
    generated = resolve_correlation_id("not-a-uuid")
    assert uuid.UUID(generated)


def test_resolve_correlation_id_generates_fresh_values_each_call():
    first = resolve_correlation_id(None)
    second = resolve_correlation_id(None)
    assert first != second
