import uuid

from reva_core.shared.ids import is_uuid7, new_id, uuid7


def test_uuid7_has_version_7():
    generated = uuid7()
    assert generated.version == 7


def test_uuid7_is_time_sortable():
    first = uuid7()
    second = uuid7()
    assert str(first) < str(second) or first.bytes[:6] <= second.bytes[:6]


def test_new_id_returns_valid_uuid7_string():
    value = new_id()
    parsed = uuid.UUID(value)
    assert parsed.version == 7


def test_is_uuid7_true_for_generated_id():
    assert is_uuid7(new_id()) is True


def test_is_uuid7_false_for_random_string():
    assert is_uuid7("not-a-uuid") is False


def test_is_uuid7_false_for_uuid4():
    assert is_uuid7(str(uuid.uuid4())) is False


def test_uuid7_ids_are_unique():
    ids = {new_id() for _ in range(1000)}
    assert len(ids) == 1000
