from datetime import UTC, datetime

import pytest
from pydantic import ValidationError as PydanticValidationError

from reva_core.shared.contracts.base import RevaBaseModel, UtcDatetime, VersionedModel


class _Sample(VersionedModel):
    created_at: UtcDatetime


def test_versioned_model_defaults_schema_version_to_1():
    sample = _Sample(created_at=datetime(2026, 1, 1, tzinfo=UTC))
    assert sample.schema_version == 1


def test_utc_datetime_rejects_naive_value():
    with pytest.raises(PydanticValidationError):
        _Sample(created_at=datetime(2026, 1, 1))  # naive


def test_reva_base_model_forbids_unknown_fields():
    class Strict(RevaBaseModel):
        name: str

    with pytest.raises(PydanticValidationError):
        Strict(name="a", unexpected="b")


def test_reva_base_model_is_frozen():
    class Strict(RevaBaseModel):
        name: str

    instance = Strict(name="a")
    with pytest.raises(PydanticValidationError):
        instance.name = "b"
