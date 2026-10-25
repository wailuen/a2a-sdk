"""Size-capped request body read (GH-246).

``request.body()`` buffers the whole upload before any cap can run. This
helper refuses a declared over-cap Content-Length before reading, otherwise
reads ``request.stream()`` and stops as soon as the cap is passed. Over-cap is
a signal (``BodyTooLarge``), not a response, so each caller keeps its own reply.
"""

from __future__ import annotations

from starlette.requests import Request

from .media import normalize_media_type


class BodyTooLarge(Exception):
    """The request body is over the cap. Carries no body data (SI-2)."""


async def read_capped_body(request: Request, cap: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > cap:
                raise BodyTooLarge
        except ValueError:
            pass
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > cap:
            raise BodyTooLarge
    return bytes(raw)


def is_json_content_type(content_type: str | None) -> bool:
    """True for ``application/json`` or a ``+json`` structured suffix type,
    ignoring case and parameters. Wildcards, ``application/json-seq`` and an
    empty value are not JSON; a caller that lets a missing header through
    checks for emptiness itself (GH-251)."""
    media = normalize_media_type(content_type or "")
    if media == "application/json":
        return True
    kind, _, subtype = media.partition("/")
    return bool(kind) and "*" not in media and subtype.endswith("+json") and len(subtype) > 5
