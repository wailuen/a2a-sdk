"""IANA time-zone loading for the per-task date line (GH-154).

``zoneinfo`` reads zone data from the host (``/usr/share/zoneinfo``) and falls
back to the ``tzdata`` package. Windows, Alpine and distroless images ship no
host zone data, so the SDK depends on ``tzdata`` — and the default zone
``"UTC"`` never touches zone data at all (``datetime.timezone.utc``), so the
default configuration boots even if both sources are missing.
"""

from __future__ import annotations

from datetime import timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MAX_TZ_LEN = 64


def load_zone(name: str) -> tzinfo:
    """Return the tzinfo for ``name``. Raises like ``ZoneInfo`` on a bad name."""
    if name == "UTC":
        return timezone.utc
    return ZoneInfo(name)


def valid_timezone(raw: object) -> str | None:
    """Return ``raw`` if it is a loadable IANA zone name, else ``None``.
    Never raises and never echoes the rejected value (SI-2)."""
    if not isinstance(raw, str) or not raw or len(raw) > MAX_TZ_LEN:
        return None
    try:
        load_zone(raw)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None
    return raw
