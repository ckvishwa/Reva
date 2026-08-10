import uuid

import pytest
from pydantic import ValidationError as PydanticValidationError

from reva_core.api.schemas import (
    ExplicitMemoryCreateRequest,
    MemoryQueryRequest,
    TypedRequest,
)


def test_typed_request_accepts_normal_content():
    request = TypedRequest(content="hello REVA")
    assert request.content == "hello REVA"


def test_typed_request_strips_whitespace():
    request = TypedRequest(content="  hello  ")
    assert request.content == "hello"


def test_typed_request_rejects_empty_content():
    with pytest.raises(PydanticValidationError):
        TypedRequest(content="")


def test_typed_request_rejects_whitespace_only_content():
    with pytest.raises(PydanticValidationError):
        TypedRequest(content="   ")


def test_typed_request_rejects_oversized_content():
    with pytest.raises(PydanticValidationError):
        TypedRequest(content="x" * 4001)


def test_typed_request_accepts_content_at_max_length():
    request = TypedRequest(content="x" * 4000)
    assert len(request.content) == 4000


def test_typed_request_accepts_valid_correlation_id():
    cid = str(uuid.uuid4())
    request = TypedRequest(content="hi", correlation_id=cid)
    assert request.correlation_id == cid


def test_typed_request_correlation_id_defaults_to_none():
    request = TypedRequest(content="hi")
    assert request.correlation_id is None


def test_explicit_memory_request_rejects_empty_content():
    with pytest.raises(PydanticValidationError):
        ExplicitMemoryCreateRequest(content="")


def test_explicit_memory_request_rejects_oversized_content():
    with pytest.raises(PydanticValidationError):
        ExplicitMemoryCreateRequest(content="x" * 8001)


def test_explicit_memory_request_defaults_category_to_note():
    request = ExplicitMemoryCreateRequest(content="hi")
    assert request.category.value == "note"


def test_explicit_memory_request_rejects_too_many_tags():
    with pytest.raises(PydanticValidationError):
        ExplicitMemoryCreateRequest(content="hi", tags=tuple(f"tag{i}" for i in range(17)))


def test_explicit_memory_request_accepts_max_tags():
    request = ExplicitMemoryCreateRequest(content="hi", tags=tuple(f"tag{i}" for i in range(16)))
    assert len(request.tags) == 16


def test_memory_query_request_rejects_empty_query():
    with pytest.raises(PydanticValidationError):
        MemoryQueryRequest(query="")


def test_memory_query_request_default_limit():
    request = MemoryQueryRequest(query="hi")
    assert request.limit == 20


def test_memory_query_request_rejects_limit_over_bound():
    with pytest.raises(PydanticValidationError):
        MemoryQueryRequest(query="hi", limit=101)


def test_memory_query_request_rejects_limit_under_bound():
    with pytest.raises(PydanticValidationError):
        MemoryQueryRequest(query="hi", limit=0)
