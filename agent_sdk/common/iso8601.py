"""Shared ISO-8601 UTC 'Z'-suffix timestamp formatting (RT-002).

Canonical fixed-width form (no microseconds, literal ``Z`` offset) used
consistently across the AG-UI route and the commitments/webhooks contrib
durable stores, so the wire/storage format contract cannot drift per module.
"""

from __future__ import annotations

from datetime import datetime, timezone


def iso_utc(value: datetime | float) -> str:
    """Format a UTC instant as ``YYYY-MM-DDTHH:MM:SSZ``.

    Accepts a POSIX timestamp (``float``/``int``, e.g. from ``time.time()``)
    or a ``datetime``. A naive ``datetime`` is treated as already UTC; an
    aware ``datetime`` is converted to UTC first.
    """
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone.utc)
    else:
        dt = datetime.fromtimestamp(value, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
