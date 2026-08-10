from datetime import UTC, datetime, timedelta, timezone

import pytest

from reva_core.shared.errors import ValidationError
from reva_core.shared.time import ensure_utc, utc_now


def test_utc_now_is_timezone_aware():
    now = utc_now()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)


def test_ensure_utc_rejects_naive_datetime():
    naive = datetime(2026, 1, 1, 12, 0, 0)
    with pytest.raises(ValidationError):
        ensure_utc(naive)


def test_ensure_utc_converts_non_utc_aware_datetime():
    eastern = timezone(timedelta(hours=-5))
    aware = datetime(2026, 1, 1, 12, 0, 0, tzinfo=eastern)
    result = ensure_utc(aware)
    assert result.tzinfo == UTC
    assert result.hour == 17


def test_ensure_utc_passes_through_utc_datetime():
    aware = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    result = ensure_utc(aware)
    assert result == aware
