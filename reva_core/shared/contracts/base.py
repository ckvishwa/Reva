"""Base types every REVA contract builds on."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict

from reva_core.shared.time import ensure_utc

UtcDatetime = Annotated[datetime, AfterValidator(ensure_utc)]
"""A datetime that must be timezone-aware; converted to UTC on validation."""


class RevaBaseModel(BaseModel):
    """Base for all REVA contracts: strict, no unknown fields, immutable."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class VersionedModel(RevaBaseModel):
    """Base for any contract that is durably stored or sent over a boundary."""

    schema_version: int = 1
