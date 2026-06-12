"""Bounded LRU rate limiting (DESIGN.md §6).

Fixed-window counters in an LRU-bounded map (an attacker rotating keys/IPs
cannot grow memory unboundedly). Client IP honors X-Forwarded-For only when
the direct peer is in AGENT_SDK_TRUSTED_PROXIES — otherwise a spoofed header
would let anyone reset their own bucket.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Callable

_MAX_KEYS = 10_000


class RateLimiter:
    def __init__(
        self,
        limit_per_minute: int,
        *,
        max_keys: int = _MAX_KEYS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = limit_per_minute
        self._max_keys = max_keys
        self._clock = clock
        self._buckets: OrderedDict[str, tuple[int, int]] = OrderedDict()  # key -> (window, count)

    def allow(self, key: str) -> bool:
        window = int(self._clock() // 60)
        prev = self._buckets.get(key)
        count = prev[1] + 1 if prev and prev[0] == window else 1
        self._buckets[key] = (window, count)
        self._buckets.move_to_end(key)
        while len(self._buckets) > self._max_keys:
            self._buckets.popitem(last=False)
        return count <= self._limit


def client_ip(
    peer_host: str | None,
    forwarded_for: str | None,
    trusted_proxies: list[str],
) -> str:
    """Effective client IP for rate-limit keys."""
    if peer_host and peer_host in trusted_proxies and forwarded_for:
        # leftmost untrusted hop
        chain = [h.strip() for h in forwarded_for.split(",") if h.strip()]
        for hop in chain:
            if hop not in trusted_proxies:
                return hop
    return peer_host or "unknown"
