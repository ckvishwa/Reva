"""UUIDv7 generation.

UUIDv7 (RFC 9562) is used for every durable entity ID instead of database
auto-increment IDs, because entities must carry stable cross-device
identity from the moment they are created — before they have ever touched
a server or a second device. UUIDv7 embeds a millisecond timestamp so IDs
remain roughly time-sortable, which keeps SQLite indexes on ID columns
useful. No compatibility blocker was found for Python 3.12, so no
third-party UUIDv7 dependency is added; the algorithm is ~10 lines.
"""

from __future__ import annotations

import os
import time
import uuid


def uuid7() -> uuid.UUID:
    """Generate a UUIDv7 per RFC 9562: unix-ms timestamp + random bits."""
    unix_ts_ms = time.time_ns() // 1_000_000
    ts_bytes = unix_ts_ms.to_bytes(6, "big")
    rand_bytes = bytearray(os.urandom(10))
    rand_bytes[0] = 0x70 | (rand_bytes[0] & 0x0F)  # version 7
    rand_bytes[2] = 0x80 | (rand_bytes[2] & 0x3F)  # variant 10
    return uuid.UUID(bytes=bytes(ts_bytes) + bytes(rand_bytes))


def new_id() -> str:
    """Generate a new UUIDv7 as its canonical string form."""
    return str(uuid7())


def is_uuid7(value: str) -> bool:
    """True if `value` parses as a UUID with version 7."""
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return parsed.version == 7
