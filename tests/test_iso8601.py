"""RT-002: single shared ISO-8601 UTC 'Z'-suffix timestamp helper."""

from __future__ import annotations

from datetime import datetime, timezone

from agent_sdk.common.iso8601 import iso_utc


def test_iso_utc_from_epoch_float():
    assert iso_utc(1_700_000_000.0) == "2023-11-14T22:13:20Z"


def test_iso_utc_from_epoch_int():
    assert iso_utc(1_700_000_000) == "2023-11-14T22:13:20Z"


def test_iso_utc_from_aware_datetime_converts_to_utc():
    dt = datetime(2026, 7, 10, 9, 30, 0, tzinfo=timezone.utc)
    assert iso_utc(dt) == "2026-07-10T09:30:00Z"


def test_iso_utc_from_naive_datetime_treats_as_utc():
    dt = datetime(2026, 7, 10, 9, 30, 0)
    assert iso_utc(dt) == "2026-07-10T09:30:00Z"


def test_iso_utc_from_non_utc_aware_datetime_normalizes():
    from datetime import timedelta

    tz = timezone(timedelta(hours=-5))
    dt = datetime(2026, 7, 10, 4, 30, 0, tzinfo=tz)
    assert iso_utc(dt) == "2026-07-10T09:30:00Z"


def test_iso_utc_always_ends_with_z_and_no_microseconds():
    dt = datetime(2026, 7, 10, 9, 30, 0, 123456, tzinfo=timezone.utc)
    result = iso_utc(dt)
    assert result.endswith("Z")
    assert "." not in result
