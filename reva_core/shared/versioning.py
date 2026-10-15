"""Protocol versions (AR-CORE-006): additive within a major, an unknown major is rejected.

A message may carry `schema_version` as "MAJOR" or "MAJOR.MINOR" (a bare integer is accepted too).
The Core speaks major 2. A higher or lower major is refused, never guessed at; a higher minor within
the same major is accepted because minors only add fields.
"""

from __future__ import annotations

from reva_core.shared.errors import ValidationError

SUPPORTED_MAJOR = 2


class UnsupportedSchemaVersion(ValidationError):
    """The message was written for a major version this Core does not speak."""


def parse_major(version: object) -> int:
    """The major number of `version`, or raise `UnsupportedSchemaVersion` if it is not a version."""
    if isinstance(version, bool):
        raise UnsupportedSchemaVersion("schema_version is not a version")
    if isinstance(version, int):
        return version
    if isinstance(version, str):
        head = version.strip().split(".", 1)[0]
        if head.isascii() and head.isdigit() and len(head) <= 4:
            return int(head)
    raise UnsupportedSchemaVersion("schema_version is not a version")


def ensure_supported(version: object, *, supported_major: int = SUPPORTED_MAJOR) -> None:
    """Accept a missing version (older clients) and the supported major; refuse anything else."""
    if version is None:
        return
    if parse_major(version) != supported_major:
        raise UnsupportedSchemaVersion(f"this Core speaks schema major {supported_major}")
