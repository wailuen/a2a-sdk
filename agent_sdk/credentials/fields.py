"""CredentialField — declared by register_source, rendered by the console."""

from __future__ import annotations

import ipaddress
import socket
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field


class CredentialField(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    label: str
    secret: bool = True
    required: bool = True
    type: Literal["string", "url"] = "string"
    help_text: str = ""


def validate_credential_url(value: str) -> str:
    """SSRF guard for url-typed credential fields (DESIGN.md §4.2).

    https-only and public-IP-only: no RFC 1918, link-local, loopback or
    metadata endpoints. Validated at save time (DNS-rebinding TOCTOU is a
    documented, accepted v1 residual — targets are operator-entered).
    """
    parsed = urlparse(value)
    if parsed.scheme != "https":
        raise ValueError("url credential fields must be https")
    host = parsed.hostname
    if not host:
        raise ValueError("url credential field has no host")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise ValueError(f"cannot resolve host {host!r}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise ValueError(f"host {host!r} resolves to a non-public address")
    return value
