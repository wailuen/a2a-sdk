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

from ..models.content_types import A2UI_EXTENSION_URI as _A2UI_EXT_URI
from ..models.content_types import A2UI_MIME_TYPE as A2UI_MIME
from ..models.content_types import A2UI_VERSION as _A2UI_VERSION
from ..models.content_types import CATALOG_ID as _STANDARD_CATALOG
from ..validation.validators import safe_id


class A2AError(Exception):
    """Raised by ChatDriver when the server returns an A2A error (§11.2 D7.10).

    Class-level constants for the seven A2A error codes (SC-E5) allow callers
    to branch on ``e.code == A2AError.TASK_NOT_FOUND`` without hardcoding ints.
    """

    # A2A §11.2 error code constants (SC-E5)
    TASK_NOT_FOUND      = -32001
    TASK_NOT_CANCELABLE = -32002
    PUSH_NOT_SUPPORTED  = -32003
    UNSUPPORTED_OP      = -32004
    CONTENT_TYPE_UNSUP  = -32005
    INVALID_AGENT_RESP  = -32006
    NOT_AUTHENTICATED   = -32007

    def __init__(self, code: int | None, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


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
        ``interrupt(task: dict)``     — A2A task paused in input-required/auth-required;
                                        passes the full task dict (may contain history)

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
        credentials: dict[str, str] | None = None,
    ) -> None:
        self._client = client
        self._caps: dict[str, Any] = {
            "version": _A2UI_VERSION,
            "tier": "core+extended",
            "catalogs": [_STANDARD_CATALOG] + list(extra_catalogs or []),
        }
        self._poll_interval = poll_interval
        self._timeout = timeout
        self._card: dict[str, Any] | None = None
        self._a2ui_active: bool = False
        # SC-E1: optional credential headers injected into every outbound request
        self._credentials: dict[str, str] | None = credentials

    def _raise_a2a_error(self, emit: dict[str, Callable] | None, response: Any) -> None:
        """Parse A2A error envelope and raise A2AError on non-2xx (§11.2 D7.10)."""
        if response.is_success:
            return
        try:
            err = response.json().get("error", {})
            code = err.get("code")
            msg = err.get("message", f"HTTP {response.status_code}")
        except Exception:
            code, msg = None, f"HTTP {response.status_code}"
        self._fire(emit, "error", f"A2A error code={code}: {msg}")
        raise A2AError(code, msg)

    def _merged_headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        """Return headers dict merging self._credentials (SC-E1) with *extra*."""
        merged: dict[str, str] = {}
        if self._credentials:
            merged.update(self._credentials)
        if extra:
            merged.update(extra)
        return merged

    async def _discover_card(self) -> dict[str, Any]:
        """Fetch and cache the agent card (A2A §11.2.1 card discovery).

        SC-E2: on 404 from /.well-known/agent-card.json, retries the legacy
        /.well-known/agent.json path before raising.
        """
        if self._card is None:
            r = await self._client.get("/.well-known/agent-card.json")
            if r.status_code == 404:
                # SC-E2: legacy fallback for A2A v0.2.x agents
                r = await self._client.get("/.well-known/agent.json")
            r.raise_for_status()
            self._card = r.json()
        return self._card

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
                    self._fire(emit, "artifact", v.get("dataType", ""), v.get("toolName", ""))
                elif custom_name == "A2UI_UPDATE":
                    msgs = (frame.get("value") or {}).get("messages") or []
                    self._fire(emit, "a2ui", msgs)
                elif t == "TEXT_MESSAGE_CONTENT":
                    delta = frame.get("delta") or ""
                    reply_parts.append(delta)
                    self._fire(emit, "text", delta)
                elif t == "RUN_ERROR":
                    self._fire(emit, "error", frame.get("message") or "run failed")
                elif t == "RUN_FINISHED":
                    outcome = frame.get("outcome") or {}
                    if outcome.get("type") == "interrupt":
                        interrupts = outcome.get("interrupts") or []
                        self._fire(emit, "interrupt", interrupts[0] if interrupts else outcome)
                    break

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
        # A2A §11.2.1 — discover card before first request; select transport
        card = await self._discover_card()
        transport = card.get("preferredTransport", "HTTP+JSON")
        _supported = ("HTTP+JSON", "JSONRPC")
        if transport not in _supported:
            # SC-E3: iterate additionalInterfaces for a supported transport fallback
            transport = None
            for iface in card.get("additionalInterfaces", []):
                t = iface.get("transport", "")
                if t in _supported:
                    transport = t
                    break
            if transport is None:
                raise ValueError(
                    f"unsupported A2A transport: {card.get('preferredTransport')!r} "
                    "and no supported transport found in additionalInterfaces"
                )

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

        # H3 (D7.11): request the A2UI extension so the server activates it
        # SC-E1: merge credentials into every outbound request
        r = await self._client.post(
            "/v1/message:send",
            json=body,
            headers=self._merged_headers({"X-A2A-Extensions": _A2UI_EXT_URI}),
        )
        self._raise_a2a_error(emit, r)
        # D7.11: confirm A2UI extension was activated by reading the response echo
        activated = [u.strip() for u in r.headers.get("x-a2a-extensions", "").split(",") if u.strip()]
        self._a2ui_active = _A2UI_EXT_URI in activated
        result = r.json()
        # H1 (D7.5): message/send can return Message OR Task — discriminate on kind
        if result.get("kind") == "message":
            return result
        task = result
        # Validate server-assigned task ID before interpolating into URL (SI-3)
        task_id = safe_id(str(task["id"]), what="task id")

        deadline = asyncio.get_running_loop().time() + self._timeout
        while True:
            await asyncio.sleep(self._poll_interval)
            g = await self._client.get(
                f"/v1/tasks/{task_id}",
                headers=self._merged_headers(),  # SC-E1: credentials on poll too
            )
            self._raise_a2a_error(emit, g)
            task = g.json()
            st = task["status"]["state"]
            self._fire(emit, "tool_done")  # re-used as poll tick
            if st in ("completed", "failed", "canceled", "rejected"):
                break
            # H2 (D7.8): surface interrupt states instead of polling to timeout
            if st in ("input-required", "auth-required"):
                self._fire(emit, "interrupt", task)
                raise A2AError(None, f"task {task_id} requires input in state {st!r}")
            if asyncio.get_running_loop().time() > deadline:
                self._fire(emit, "error", f"task {task_id} timed out in state {st!r}")
                return task

        return task

    async def resume(
        self,
        task_id: str,
        context_id: str,
        reply: str,
        *,
        emit: dict[str, Callable] | None = None,
    ) -> dict[str, Any]:
        """Resume an interrupted task (SC-E4 / A2A §7 D7.8).

        Constructs a message/send request with *task_id* and *context_id*
        to satisfy the A2A MUST that interrupted tasks continue with the
        SAME taskId + contextId.  Returns the same result as :meth:`a2a_turn`.
        """
        body: dict[str, Any] = {
            "message": {
                "kind": "message",
                "role": "user",
                "messageId": uuid.uuid4().hex,
                "taskId": task_id,
                "contextId": context_id,
                "parts": [{"kind": "text", "text": reply}],
                "metadata": {"a2uiClientCapabilities": self._caps},
            }
        }
        r = await self._client.post(
            "/v1/message:send",
            json=body,
            headers=self._merged_headers({"X-A2A-Extensions": _A2UI_EXT_URI}),
        )
        self._raise_a2a_error(emit, r)
        result = r.json()
        if result.get("kind") == "message":
            return result
        task = result
        task_id_validated = safe_id(str(task["id"]), what="task id")

        deadline = asyncio.get_running_loop().time() + self._timeout
        while True:
            await asyncio.sleep(self._poll_interval)
            g = await self._client.get(
                f"/v1/tasks/{task_id_validated}",
                headers=self._merged_headers(),
            )
            self._raise_a2a_error(emit, g)
            task = g.json()
            st = task["status"]["state"]
            self._fire(emit, "tool_done")
            if st in ("completed", "failed", "canceled", "rejected"):
                break
            if st in ("input-required", "auth-required"):
                self._fire(emit, "interrupt", task)
                raise A2AError(None, f"task {task_id_validated} requires input in state {st!r}")
            if asyncio.get_running_loop().time() > deadline:
                self._fire(emit, "error", f"task {task_id_validated} timed out in state {st!r}")
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
        """A2UI message-list sequences from task artifacts (one list per artifact).

        Dispatches on DataPart.metadata.mimeType per A2UI §A5 (the canonical
        render-hint location); not on the artifact-level mimeType shortcut.
        """
        result = []
        for art in task.get("artifacts") or []:
            for p in art.get("parts") or []:
                part_mime = (p.get("metadata") or {}).get("mimeType")
                if p.get("kind") == "data" and part_mime == A2UI_MIME:
                    if isinstance(p.get("data"), list):
                        result.append(p["data"])
        return result
