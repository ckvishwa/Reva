"""Request bodies that may state the protocol version they were written for (AR-CORE-006).

`schema_version` is optional so older clients keep working. If it is present its major must be the
one this Core speaks; any other major is refused with `unsupported_schema_version` rather than
guessed at. A newer minor within the same major is accepted, because minors only add fields.
"""

from pydantic import BaseModel, ConfigDict, field_validator

from reva_core.shared.versioning import ensure_supported


class VersionedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str | int | None = None

    @field_validator("schema_version")
    @classmethod
    def _major_is_supported(cls, value: str | int | None) -> str | int | None:
        ensure_supported(value)
        return value
