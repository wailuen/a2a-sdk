"""CORS middleware — the exact shape Claude.ai requires (DESIGN.md §5.5).

Hand-rolled ASGI middleware instead of Starlette's ``CORSMiddleware`` for two
load-bearing reasons:

- OPTIONS preflight must return **204** (Starlette returns 200).
- ``Access-Control-Expose-Headers: WWW-Authenticate`` must be present —
  without it the browser cannot read the 401 challenge and OAuth discovery
  never starts.

The allow-origin value echoes the request Origin only when it is in the
configured allowlist (``settings.cors_origins``) — never ``*``. ``Vary:
Origin`` is always set so caches never serve one origin's CORS decision to
another.

Wiring: ``app.add_middleware(CorsMiddleware, origins=settings.cors_origins)``.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Iterable

_ALLOW_METHODS = b"GET, POST, DELETE, OPTIONS"
_ALLOW_HEADERS = (
    b"Authorization, Content-Type, Mcp-Session-Id, Accept, Last-Event-ID, "
    b"MCP-Protocol-Version, X-A2A-Extensions, X-Agent-Credentials"
)
_EXPOSE_HEADERS = b"WWW-Authenticate, Mcp-Session-Id, X-A2A-Extensions"

_Scope = dict[str, Any]
_Receive = Callable[[], Awaitable[dict[str, Any]]]
_Send = Callable[[dict[str, Any]], Awaitable[None]]


def _merge_vary(headers: list[tuple[bytes, bytes]]) -> list[tuple[bytes, bytes]]:
    """Append Origin to an existing Vary header, or add one."""
    out: list[tuple[bytes, bytes]] = []
    found = False
    for name, value in headers:
        if name.lower() == b"vary":
            found = True
            values = [v.strip() for v in value.split(b",") if v.strip()]
            if not any(v.lower() == b"origin" for v in values):
                value = value + b", Origin" if value else b"Origin"
        out.append((name, value))
    if not found:
        out.append((b"vary", b"Origin"))
    return out


class CorsMiddleware:
    def __init__(self, app: Any, origins: Iterable[str] | None = None) -> None:
        self.app = app
        self._origins = frozenset(o.rstrip("/") for o in (origins or []))

    def _allowed(self, origin: bytes | None) -> bytes | None:
        if origin is None:
            return None
        try:
            decoded = origin.decode("latin-1").rstrip("/")
        except Exception:
            return None
        return origin if decoded in self._origins else None

    async def __call__(self, scope: _Scope, receive: _Receive, send: _Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        origin = self._allowed(headers.get(b"origin"))

        # Preflight: OPTIONS + Access-Control-Request-Method → answered here,
        # 204 (never reaches the app; the app has no OPTIONS handlers).
        if (
            scope.get("method") == "OPTIONS"
            and b"access-control-request-method" in headers
        ):
            response_headers: list[tuple[bytes, bytes]] = [(b"vary", b"Origin")]
            if origin is not None:
                response_headers += [
                    (b"access-control-allow-origin", origin),
                    (b"access-control-allow-methods", _ALLOW_METHODS),
                    (b"access-control-allow-headers", _ALLOW_HEADERS),
                ]
            await send(
                {
                    "type": "http.response.start",
                    "status": 204,
                    "headers": response_headers,
                }
            )
            await send({"type": "http.response.body", "body": b""})
            return

        async def send_with_cors(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers", []))
                if origin is not None:
                    response_headers += [
                        (b"access-control-allow-origin", origin),
                        (b"access-control-expose-headers", _EXPOSE_HEADERS),
                    ]
                message = {**message, "headers": _merge_vary(response_headers)}
            await send(message)

        await self.app(scope, receive, send_with_cors)
