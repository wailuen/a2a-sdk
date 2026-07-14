"""Shared Origin allow-list guard (RT-004, C-009).

Defense-in-depth check for every browser-reachable route (A2A, AG-UI, MCP
Streamable HTTP + legacy SSE): a present ``Origin`` header not on
``request.app.state.cors_origins`` is rejected outright. ``routes/mcp.py`` had
the identical inline block re-implemented at 5 call sites (``mcp_post``,
``mcp_get``, ``mcp_delete``, ``mcp_sse``, ``mcp_messages``); those 5 were
extracted into this shared helper. ``routes/a2a.py`` (6 handlers) and
``routes/ag_ui.py`` (``ag_ui_run``) had no Origin checking at all before this
change — they are newly guarded here for the first time, not deduplicated
from an existing copy. Any future fix (handling a ``null`` Origin, subdomain
matching, case-folding, …) must land here once rather than risk drifting one
call site out of sync with the rest.
"""

from __future__ import annotations

from fastapi import HTTPException, Request


def guard_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin is not None and origin not in request.app.state.cors_origins:
        raise HTTPException(status_code=403, detail="origin not allowed")
