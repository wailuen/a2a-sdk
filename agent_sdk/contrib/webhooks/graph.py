"""build_graph_webhook_router — the inbound HTTP edge for Graph webhooks (§9).

EXPERIMENTAL (DESIGN §4.0).

A factory returning a FastAPI ``APIRouter`` the integrator mounts *after* the app
is built (DESIGN §10.3, ``app.include_router(...)``) — the SDK core gains no
inbound-route knowledge. The route does exactly two things and nothing slow:

- **Validation handshake.** When Graph (or you, at subscription create/renew)
  POSTs ``?validationToken=<token>``, echo the URL-decoded token back verbatim as
  ``text/plain`` with ``200 OK``. Starlette already percent-decodes query params;
  an over-long token (never sent by Graph) is rejected ``400`` rather than
  reflected. Both ``notificationUrl`` and ``lifecycleNotificationUrl`` are
  validated this way — mount the router on each path you registered.
- **Notification intake.** Read the body (size-capped), hand it to
  ``dispatcher.schedule(...)`` for background processing, and **always answer 202
  Accepted** — within Graph's 3-second budget, regardless of handler latency. A
  malformed body is dropped (still 202): a 4xx/5xx would make Graph retry for 4
  hours and, on sustained slowness, drop the subscription.

**This route is deliberately unauthenticated.** Graph presents no bearer token;
authenticity is established by ``clientState`` inside the body (validated by the
dispatcher, constant-time), not by transport auth. Do NOT add
``Depends(require_identity)``. DO pass ``dependencies=[Depends(unauth_rate_limit)]``
to bound per-IP flooding of this public endpoint.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Sequence

from fastapi import APIRouter, Request, Response
from fastapi.responses import PlainTextResponse

from .dispatch import WebhookDispatcher

logger = logging.getLogger("agent_sdk.contrib.webhooks")

# Graph validationToken values are short opaque strings; anything large is not
# from Graph and must not be reflected (amplification / abuse).
_MAX_TOKEN_LEN = 2048
# Graph batches are small; 1 MiB is generous headroom and caps parse cost.
_MAX_BODY_BYTES = 1 << 20


def _accepted() -> Response:
    # Fresh instance per response (a Response is an ASGI app; don't share state).
    return Response(status_code=202)


def build_graph_webhook_router(
    dispatcher: WebhookDispatcher,
    *,
    path: str = "/webhooks/graph",
    lifecycle_path: str | None = None,
    max_token_length: int = _MAX_TOKEN_LEN,
    max_body_bytes: int = _MAX_BODY_BYTES,
    dependencies: Sequence[Any] | None = None,
) -> APIRouter:
    """Build an ``APIRouter`` that receives Graph change/lifecycle notifications.

    ``lifecycle_path`` mounts the identical handler on a second path for
    deployments whose ``lifecycleNotificationUrl`` differs from
    ``notificationUrl`` (the dispatcher branches on ``lifecycleEvent`` regardless
    of which path delivered the POST).
    """
    router = APIRouter(dependencies=list(dependencies) if dependencies else None)
    token_cap = max(1, int(max_token_length))
    body_cap = max(1, int(max_body_bytes))

    async def _receive(request: Request) -> Response:
        # 1) Validation handshake — opaque token echoed as text/plain.
        token = request.query_params.get("validationToken")
        if token is not None:
            if len(token) > token_cap:
                logger.warning("webhooks: oversized validationToken rejected")
                return Response(status_code=400)
            # text/plain (not executed by browsers) + nosniff defends a legacy
            # MIME-sniffing client against the reflected, opaque token.
            return PlainTextResponse(
                token,
                status_code=200,
                headers={"X-Content-Type-Options": "nosniff"},
            )

        # 2) Notification intake — size-capped read, schedule, always 202.
        # Content-Length is a fast-path hint only; a chunked or lying header
        # would bypass it, so the streamed read below is the real cap.
        declared = request.headers.get("content-length")
        if declared is not None:
            try:
                if int(declared) > body_cap:
                    logger.warning("webhooks: oversized body rejected (content-length)")
                    return _accepted()  # drop, but do not invite a Graph retry storm
            except ValueError:
                pass
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > body_cap:  # abort as soon as the cap is exceeded
                logger.warning("webhooks: oversized body dropped")
                return _accepted()
        try:
            payload = json.loads(raw) if raw else None
        except (ValueError, UnicodeDecodeError):
            logger.warning("webhooks: non-JSON body dropped")
            return _accepted()
        if payload is not None:
            dispatcher.schedule(payload)
        return _accepted()

    router.add_api_route(path, _receive, methods=["POST"], include_in_schema=False)
    if lifecycle_path and lifecycle_path != path:
        router.add_api_route(
            lifecycle_path, _receive, methods=["POST"], include_in_schema=False
        )
    return router


__all__ = ["build_graph_webhook_router"]
