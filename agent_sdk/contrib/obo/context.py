"""Per-request assertion threading for OBO (DESIGN.md §9).

The OBO exchange needs the inbound user-assertion JWT, but the SDK runs the
agent loop in a worker task that is *detached* from the request (the A2A route
spawns it with ``create_task``, which snapshots the current context). So the
assertion is carried the same way ``credentials.forwarding`` carries vendor
keys: a request-scoped :class:`contextvars.ContextVar`. The worker inherits the
snapshot; a :class:`~agent_sdk.contrib.obo.GraphSource` reads it via
:func:`current_assertion` at tool time.

:class:`OboAssertionMiddleware` is a **pure-ASGI** middleware (NOT
``BaseHTTPMiddleware`` — that runs the downstream app in a separate task and
breaks contextvar propagation into the worker snapshot). Install it on the built
app via the documented escape hatch (DESIGN §10.3)::

    app = agent.build_app()
    app.add_middleware(OboAssertionMiddleware)        # before startup

It binds ONLY a structurally JWT-shaped Bearer — a token that is not three
base64url segments (most opaque API keys) is not bound. This is a *shape* filter,
not validation: a non-Entra JWT (or any three-segment base64url string) would
still bind. The token is never verified here — that is the route's auth
``Depends`` and, ultimately, MSAL at exchange time; the assertion is only ever
*used* if the request passes auth and reaches a tool, and a wrong-audience or
forged token fails closed at MSAL (and at the audience pre-check in
:class:`~agent_sdk.contrib.obo.OboExchanger`).

**Deployment constraint (surface this):** OBO requires the inbound Bearer to be
an *Entra-issued* user assertion whose audience is this agent's app registration.
Whether the SDK's own auth (API key / SDK-issued OAuth token) carries such an
assertion is deployment-specific — the m365 port wires its front door so the
inbound token is an Entra token. If it is not, the exchange fails closed at MSAL.

**Secrets hygiene:** this module never logs the token, the header, or any value.
"""

from __future__ import annotations

import contextvars
import re

# Three non-empty base64url segments — the JWT shape. An opaque API key (no dots,
# or non-base64url chars) is rejected so it is never mistaken for an assertion.
_B64URL_SEGMENT = re.compile(r"^[A-Za-z0-9_-]+$")

_assertion: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "agent_sdk_obo_assertion", default=None
)


def looks_like_assertion(token: str) -> bool:
    """True iff ``token`` is JWT-shaped (header.payload.signature, all base64url).
    Structural only — no signature or claim validation."""
    parts = token.split(".")
    if len(parts) != 3 or not all(parts):
        return False
    return all(_B64URL_SEGMENT.match(p) for p in parts)


def bind_assertion(token: str | None) -> contextvars.Token:
    """Install the assertion for the current context; returns a reset token.
    A non-JWT (or ``None``/empty) value binds ``None`` so a downstream exchange
    fails closed with 'no user assertion' rather than feeding junk to MSAL."""
    value = token if (token and looks_like_assertion(token)) else None
    return _assertion.set(value)


def unbind_assertion(token: contextvars.Token) -> None:
    _assertion.reset(token)


def current_assertion() -> str | None:
    """The inbound user assertion for this request/worker, or ``None``."""
    return _assertion.get()


def _bearer_from_scope(scope: dict) -> str | None:
    """Extract a Bearer token from an ASGI scope's headers (case-insensitive),
    or ``None``. Header values are bytes in ASGI. Iterates ALL ``authorization``
    headers and returns the first Bearer — a non-Bearer scheme on one header (or a
    malformed value) does not short-circuit a later Bearer."""
    for name, value in scope.get("headers", []):
        if name != b"authorization":
            continue
        try:
            text = value.decode("latin-1")
        except Exception:
            continue
        if text[:7].lower() == "bearer ":
            token = text[7:].strip()
            if token:
                return token
    return None


class OboAssertionMiddleware:
    """Pure-ASGI middleware that binds a JWT-shaped inbound Bearer as the OBO
    assertion for the request (and the worker it spawns)."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        token = _bearer_from_scope(scope)
        reset = bind_assertion(token)
        try:
            await self.app(scope, receive, send)
        finally:
            # The worker (create_task) already copied this context; resetting
            # here scrubs the request task without disturbing the worker snapshot.
            unbind_assertion(reset)


__all__ = [
    "OboAssertionMiddleware",
    "bind_assertion",
    "unbind_assertion",
    "current_assertion",
    "looks_like_assertion",
]
