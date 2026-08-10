import uuid
from datetime import UTC, datetime

from reva_core.api.schemas import (
    ErrorResponse,
    ExplicitMemoryCreateRequest,
    ExplicitMemoryCreateResponse,
    MemoryQueryResponse,
    MemoryQueryResponseItem,
    TypedRequest,
    TypedResponse,
)
from reva_core.shared.contracts.memory import MemoryCategory, MemorySourceReference


def _round_trip(model):
    cls = type(model)
    restored = cls.model_validate_json(model.model_dump_json())
    assert restored == model
    assert restored.schema_version == 1


def test_typed_request_round_trip():
    _round_trip(TypedRequest(content="hello", correlation_id=str(uuid.uuid4())))


def test_typed_response_round_trip():
    _round_trip(TypedResponse(correlation_id=str(uuid.uuid4()), reply="ack", memory_created=None))


def test_explicit_memory_create_request_round_trip():
    _round_trip(
        ExplicitMemoryCreateRequest(
            content="remember this", category=MemoryCategory.DECISION, tags=("a", "b")
        )
    )


def test_explicit_memory_create_response_round_trip():
    _round_trip(
        ExplicitMemoryCreateResponse(
            id=_uuid7(),
            category=MemoryCategory.NOTE,
            created_at=datetime.now(UTC),
            correlation_id=str(uuid.uuid4()),
        )
    )


def test_memory_query_response_round_trip():
    item = MemoryQueryResponseItem(
        id=_uuid7(),
        content="content",
        category=MemoryCategory.NOTE,
        source=MemorySourceReference(origin_device_id=_uuid7(), note="x"),
        tags=("tag1",),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    _round_trip(MemoryQueryResponse(results=(item,), correlation_id=str(uuid.uuid4())))


def test_error_response_round_trip_with_and_without_correlation_id():
    _round_trip(ErrorResponse(error="Unauthorized", correlation_id=str(uuid.uuid4())))
    _round_trip(ErrorResponse(error="internal_error", correlation_id=None))


def test_memory_category_enum_values_stable():
    assert {c.value for c in MemoryCategory} == {
        "fact",
        "preference",
        "decision",
        "note",
        "project_context",
    }


def _uuid7() -> str:
    from reva_core.shared.ids import new_id

    return new_id()
