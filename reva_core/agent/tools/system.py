"""`get_current_time` — a trivial, stateless tool.

No REVA-specific infrastructure needed: it wraps the one existing
UTC-time abstraction (`reva_core.shared.time.utc_now`) that every
durable timestamp in Core already goes through.
"""

from __future__ import annotations

from typing import Any

from reva_core.shared.time import utc_now


def get_current_time() -> dict[str, Any]:
    """Return the current date and time in UTC.

    Returns:
      A dict with "status" and an ISO-8601 UTC "current_time_utc" string.
    """
    return {"status": "success", "current_time_utc": utc_now().isoformat()}
