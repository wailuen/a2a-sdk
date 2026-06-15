"""SSRF-safe HTTP utilities (DESIGN.md §4.2).

``safe_get`` is the approved escape hatch for tool code that must fetch a
user-supplied URL outside a SourceAdapter.  SI-1 bans bare httpx in tools;
use this instead.

``_is_non_public_ip`` is the shared IP-block predicate consumed by
SourceAdapter._on_request and validate_credential_url — single source of truth
for the RFC 1918 / loopback / link-local / reserved / multicast deny-list.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket

import httpx

from agent_sdk.models.errors import AgentError, ErrorCategory


def _is_non_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


async def safe_get(url: str, *, timeout: float = 30.0) -> httpx.Response:
    """GET ``url`` after verifying the resolved IP is public.

    Raises ``AgentError(VALIDATION)`` for non-public targets (RFC 1918,
    loopback, link-local 169.254.x.x, reserved, multicast).  ``follow_redirects``
    is False — callers must handle 3xx explicitly to avoid open-redirect SSRF.
    """
    from urllib.parse import urlparse

    host = urlparse(url).hostname or ""
    if not host:
        raise AgentError(ErrorCategory.VALIDATION, "safe_get: url has no host")
    try:
        loop = asyncio.get_running_loop()
        infos = await loop.getaddrinfo(host, None)
    except socket.gaierror:
        raise AgentError(ErrorCategory.VALIDATION, f"safe_get: cannot resolve host '{host}'")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if _is_non_public_ip(ip):
            raise AgentError(
                ErrorCategory.VALIDATION,
                f"safe_get: '{host}' resolves to a non-public address",
            )
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        return await client.get(url)
