"""ChatDriver — live chat driver for integration and manual testing.

Drives a single A2A or AG-UI turn against a live agent via an
``httpx.AsyncClient``.  Used by ``python -m agent_sdk test-chat`` and
usable directly in integration tests that need a human-readable turn.

A2UI caps are declared automatically (``tier=core+extended``, standard-profile
catalog always included); pass ``extra_catalogs`` for domain catalogs.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Callable

from ..models.content_types import CATALOG_ID as _STANDARD_CATALOG

A2UI_MIME = "application/a2ui+json"


class ChatDriver:
    """Protocol driver for live turn-by-turn chat against a booted agent.

    Both AG-UI and A2A modes are supported.  The ``emit`` dict passed to each
    turn method is a lightweight event bus — callers subscribe to any subset of
    keys and receive plain Python values; the rest are silently dropped.

    Emit keys:
        ``tool_start(name: str)``     — tool call begins
        ``tool_args(args: dict)``     — parsed tool arguments
        ``tool_done()``               — tool call ends (result received)
        ``artifact(data_type, tool)`` — artifact emitted before result
        ``a2ui(messages: list)``      — A2UI 4-message lifecycle sequence
        ``text(delta: str)``          — streaming text delta (AG-UI only)
        ``error(message: str)``       — run or request error

    Example::

        driver = ChatDriver(client, extra_catalogs=["urn:acme:v1"])
        thread_id = uuid.uuid4().hex
        messages: list[dict] = []
        text = await driver.agui_turn(
            "What is the climate risk for NYC?",
            thread_id, messages,
            emit={"text": print, "tool_start": lambda n: print(f"  [tool] {n}")},
        )
    """

    def __init__(
        self,
        client: Any,  # httpx.AsyncClient
        *,
        extra_catalogs: list[str] | None = None,
        poll_interval: float = 0.5,
        timeout: float = 180.0,
    ) -> None:
        self._client = client
        self._caps: dict[str, Any] = {
            "tier": "core+extended",
            "catalogs": [_STANDARD_CATALOG] + list(extra_catalogs or []),
        }
        self._poll_interval = poll_interval
        self._timeout = timeout

    def _fire(self, emit: dict[str, Callable] | None, key: str, *args: Any) -> None:
        if emit:
            fn = emit.get(key)
            if callable(fn):
                fn(*args)

    # ── AG-UI ─────────────────────────────────────────────────────────────────

    async def agui_turn(
        self,
        query: str,
        thread_id: str,
        messages: list[dict[str, Any]],
        *,
        emit: dict[str, Callable] | None = None,
    ) -> str:
        """One AG-UI turn over ``POST /ag-ui/run`` (SSE).

        Appends ``{role: user}`` and ``{role: assistant}`` to *messages* in-place
        for multi-turn continuity.  Returns the assistant reply text.
        """
        messages.append({"role": "user", "content": query})
        body = {
            "threadId": thread_id,
            "runId": uuid.uuid4().hex,
            "messages": list(messages),
            "forwardedProps": {"a2uiClientCapabilities": self._caps},
            "state": {},
        }
        reply_parts: list[str] = []
        _pending_tool: str | None = None

        async with self._client.stream("POST", "/ag-ui/run", json=body) as resp:
            resp.raise_for_status()
            async for raw in resp.aiter_lines():
                raw = raw.strip()
                if not raw.startswith("data:"):
                    continue
                frame = json.loads(raw[5:].strip())
                t = frame.get("type")
                custom_name = frame.get("name") if t == "CUSTOM" else None

                if t == "TOOL_CALL_START":
                    _pending_tool = frame.get("toolCallName", "")
                    self._fire(emit, "tool_start", _pending_tool)
                elif t == "TOOL_CALL_ARGS":
                    try:
                        args = json.loads(frame.get("delta") or "{}")
                        self._fire(emit, "tool_args", args)
                    except (ValueError, TypeError):
                        pass
                elif t == "TOOL_CALL_RESULT":
                    self._fire(emit, "tool_done")
                    _pending_tool = None
                elif custom_name == "AGENT_ARTIFACT":
                    v = frame.get("value") or {}
                    self._fire(emit, "artifact", v.get("data_type", ""), v.get("tool_name", ""))
                elif custom_name == "A2UI_UPDATE":
                    msgs = (frame.get("value") or {}).get("messages") or []
                    self._fire(emit, "a2ui", msgs)
                elif t == "TEXT_MESSAGE_CONTENT":
                    delta = frame.get("delta") or ""
                    reply_parts.append(delta)
                    self._fire(emit, "text", delta)
                elif t == "RUN_ERROR":
                    self._fire(emit, "error", frame.get("message") or "run failed")

        reply = "".join(reply_parts)
        if reply:
            messages.append({"role": "assistant", "content": reply})
        return reply

    # ── A2A ───────────────────────────────────────────────────────────────────

    async def a2a_turn(
        self,
        query: str,
        context_id: str | None = None,
        *,
        emit: dict[str, Callable] | None = None,
    ) -> dict[str, Any]:
        """One A2A turn: ``POST /v1/message:send`` then poll to terminal state.

        Returns the completed task dict.  Use :meth:`extract_reply` and
        :meth:`extract_a2ui` to pull structured data from it.

        ``emit`` keys used here:
            ``tool_done()`` — fired on each poll tick (progress signal)
            ``error(message)`` — fired on timeout or non-completed terminal state
        """
        body: dict[str, Any] = {
            "message": {
                "kind": "message",
                "role": "user",
                "messageId": uuid.uuid4().hex,
                "parts": [{"kind": "text", "text": query}],
                "metadata": {"a2uiClientCapabilities": self._caps},
            }
        }
        if context_id:
            body["message"]["contextId"] = context_id

        r = await self._client.post("/v1/message:send", json=body)
        r.raise_for_status()
        task = r.json()
        task_id = task["id"]

        deadline = asyncio.get_event_loop().time() + self._timeout
        while True:
            await asyncio.sleep(self._poll_interval)
            g = await self._client.get(f"/v1/tasks/{task_id}")
            g.raise_for_status()
            task = g.json()
            st = task["status"]["state"]
            self._fire(emit, "tool_done")  # re-used as poll tick
            if st in ("completed", "failed", "canceled", "rejected"):
                break
            if asyncio.get_event_loop().time() > deadline:
                self._fire(emit, "error", f"task {task_id} timed out in state {st!r}")
                return task

        return task

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def extract_reply(task: dict[str, Any]) -> str:
        """First agent-role text reply from a completed task's history."""
        for msg in task.get("history") or []:
            if msg.get("role") == "agent":
                parts = [
                    p.get("text", "")
                    for p in (msg.get("parts") or [])
                    if p.get("kind") == "text" and p.get("text")
                ]
                if parts:
                    return "\n".join(parts)
        return ""

    @staticmethod
    def extract_a2ui(task: dict[str, Any]) -> list[list[dict[str, Any]]]:
        """A2UI message-list sequences from task artifacts (one list per artifact)."""
        result = []
        for art in task.get("artifacts") or []:
            meta = art.get("metadata") or {}
            if meta.get("mimeType") != A2UI_MIME:
                continue
            for p in art.get("parts") or []:
                if p.get("kind") == "data" and isinstance(p.get("data"), list):
                    result.append(p["data"])
        return result
