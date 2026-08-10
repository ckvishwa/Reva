import uuid

import pytest
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from reva_core.shared.contracts.ids import CorrelationId, DeviceId, EntityId
from reva_core.shared.ids import new_id


class _Holder(BaseModel):
    entity_id: EntityId
    device_id: DeviceId
    correlation_id: CorrelationId


def test_entity_id_accepts_uuid7():
    holder = _Holder(entity_id=new_id(), device_id=new_id(), correlation_id=str(uuid.uuid4()))
    assert holder.entity_id


def test_entity_id_rejects_uuid4():
    with pytest.raises(PydanticValidationError):
        _Holder(entity_id=str(uuid.uuid4()), device_id=new_id(), correlation_id=str(uuid.uuid4()))


def test_entity_id_rejects_non_uuid_string():
    with pytest.raises(PydanticValidationError):
        _Holder(entity_id="not-a-uuid", device_id=new_id(), correlation_id=str(uuid.uuid4()))


def test_correlation_id_accepts_any_uuid_version():
    holder = _Holder(entity_id=new_id(), device_id=new_id(), correlation_id=str(uuid.uuid4()))
    assert holder.correlation_id


def test_correlation_id_rejects_non_uuid_string():
    with pytest.raises(PydanticValidationError):
        _Holder(entity_id=new_id(), device_id=new_id(), correlation_id="not-a-uuid")
