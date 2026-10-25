"""Throttled, retrying turn helper for live A2A and AG-UI acceptance runs (GH-210).

PROVISIONAL (``agent_sdk.testing``).  Each call runs one turn against a booted
agent.  A cross-process slot limit (file locks) caps concurrent in-flight
turns, and rate-limit style failures are retried with exponential back-off
inside a total time budget.

Security: the API key is read from ``key_file`` only (never an argument value
or env var) and is never written to state/lock files or logs.  Log lines and
the failure record carry only a status code, an attempt count and fixed reason
text, never headers, the query, or response bodies.

Non-goal: A2A ``additionalInterfaces`` and the card ``url`` are not followed; the
turn always goes to ``/v1/message:stream`` on the client it is given.

CLI::

    ACC_QUERY="..." python -m agent_sdk.testing.turns --transport a2a|agui \
        --base-url URL --key-file PATH --run-key KEY [--slots N]
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import fcntl
import json
import logging
import os
import re
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from .chat import MALFORMED_STREAM_TEXT, ChatDriver, card_catalog_ids, fetch_agent_card

logger = logging.getLogger("agent_sdk.testing.turns")

DEFAULT_SLOTS = 3
DEFAULT_BUDGET_S = 540.0
_BACKOFF_BASE_S = 2.0
_BACKOFF_CAP_S = 60.0
_SLOT_POLL_S = 1.0
_RATE_TEXT = ("too many requests", "rate limit")

_sleep = asyncio.sleep
_now = time.monotonic


class Slot:
    def __init__(self, fd: int) -> None:
        self._fd: int | None = fd

    def release(self) -> None:
        if self._fd is not None:
            with contextlib.suppress(OSError):
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            os.close(self._fd)
            self._fd = None


class SlotLimiter:
    """At most *slots* holders at once across all processes sharing *lock_dir*."""

    def __init__(self, lock_dir: str | Path, slots: int = DEFAULT_SLOTS) -> None:
        self._dir = Path(lock_dir)
        self._slots = max(1, slots)

    def try_acquire(self) -> Slot | None:
        self._dir.mkdir(parents=True, exist_ok=True)
        for i in range(self._slots):
            fd = os.open(self._dir / f"slot-{i}.lock", os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                os.close(fd)
                continue
            return Slot(fd)
        return None

    async def acquire(self, deadline: float) -> Slot | None:
        while True:
            slot = self.try_acquire()
            if slot is not None:
                return slot
            if _now() + _SLOT_POLL_S > deadline:
                return None
            await _sleep(_SLOT_POLL_S)


class _Attempt:
    def __init__(self) -> None:
        self.reply = ""
        self.content_types: list[str] = []
        self.tools: list[str] = []
        self.status: int | None = None
        self.rate_limited = False
        self.failed = False
        self.reason = ""
        self.error_text = ""
        self.ids: dict[str, str] = {}

    def classify(self) -> bool:
        """Return True when the attempt succeeded; set reason otherwise."""
        if self.status == 429:
            self.rate_limited, self.reason = True, "http-429"
        elif self.status is not None:
            self.reason = "http-error"
        elif self.reason in ("transport-error", "malformed-stream"):
            pass
        elif any(t in self.error_text.lower() for t in _RATE_TEXT):
            self.rate_limited, self.reason = True, "too-many-requests"
        elif self.failed:
            self.reason = "task-failed"
        elif not self.reply and not self.content_types:
            self.reason = "empty-reply"
        else:
            return True
        return False


def _safe(run_key: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", run_key)


async def _card_driver(client: httpx.AsyncClient) -> ChatDriver:
    """A ChatDriver whose catalogs include the card's ``supportedCatalogIds``.

    A 429 or 5xx card response propagates as ``httpx.HTTPStatusError`` so the
    attempt fails and is retried; any other failure or a non-object card counts
    as an agent that does not advertise A2UI.
    """
    card: Any = {}
    try:
        card = await fetch_agent_card(client)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 429 or exc.response.status_code >= 500:
            raise
        logger.warning("agent card fetch failed: %s", type(exc).__name__)
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("agent card fetch failed: %s", type(exc).__name__)
    if not isinstance(card, dict):
        card = {}
    return ChatDriver(client, extra_catalogs=card_catalog_ids(card), card=card)


class _MalformedStream(Exception):
    pass


def _obj(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise _MalformedStream
    return value


def _str_of(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise _MalformedStream
    return value


def _text_of(parts: Any) -> str:
    if parts is None:
        return ""
    if not isinstance(parts, list):
        raise _MalformedStream
    texts = [p.get("text") for p in parts if isinstance(p, dict) and p.get("kind") == "text"]
    strs = [t for t in texts if isinstance(t, str)]
    if len(strs) != len(texts):
        raise _MalformedStream
    return "\n".join(strs)


def _card_failed(at: _Attempt, exc: httpx.HTTPStatusError) -> _Attempt:
    at.status = exc.response.status_code
    at.classify()
    return at


async def _a2a_attempt(
    client: httpx.AsyncClient,
    query: str,
    state: dict[str, str],
    driver: ChatDriver | None = None,
) -> _Attempt:
    at = _Attempt()
    try:
        driver = driver or await _card_driver(client)
    except httpx.HTTPStatusError as exc:
        return _card_failed(at, exc)
    msg: dict[str, Any] = {
        "kind": "message",
        "role": "user",
        "messageId": uuid.uuid4().hex,
        "parts": [{"kind": "text", "text": query}],
    }
    headers, meta = await driver.a2ui_client_activation()
    if meta:
        msg["metadata"] = meta
    if state.get("task_id") and state.get("state") in ("input-required", "auth-required"):
        msg["taskId"] = state["task_id"]
    if state.get("context_id"):
        msg["contextId"] = state["context_id"]
    task_id = ctx_id = cur_state = ""
    message_seen = False
    try:
        async with client.stream(
            "POST", "/v1/message:stream", json={"message": msg}, headers=headers
        ) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line.startswith("data:"):
                    continue
                try:
                    ev = json.loads(line[5:].strip())
                except ValueError:
                    at.reason = "malformed-stream"
                    break
                if not isinstance(ev, dict):
                    at.reason = "malformed-stream"
                    break
                kind = ev.get("kind")
                if kind == "task":
                    task_id = task_id or _str_of(ev.get("id"))
                    ctx_id = ctx_id or _str_of(ev.get("contextId"))
                elif kind == "status-update":
                    task_id = task_id or _str_of(ev.get("taskId"))
                    ctx_id = ctx_id or _str_of(ev.get("contextId"))
                    status = _obj(ev.get("status"))
                    st = _str_of(status.get("state"))
                    if st:
                        cur_state = st
                    if ev.get("final") or st == "completed":
                        at.reply = _text_of(_obj(status.get("message")).get("parts"))
                    if ev.get("final"):
                        break
                elif kind == "message":
                    task_id = task_id or _str_of(ev.get("taskId"))
                    ctx_id = ctx_id or _str_of(ev.get("contextId"))
                    at.reply = _text_of(ev.get("parts"))
                    message_seen = True
                    break
                elif kind == "artifact-update":
                    art = _obj(ev.get("artifact"))
                    dtype = _obj(art.get("metadata")).get("data_type") or art.get("name")
                    parts = art.get("parts") or []
                    if not isinstance(parts, list):
                        raise _MalformedStream
                    for part in parts:
                        if isinstance(part, dict) and part.get("kind") == "data":
                            meta = _obj(part.get("metadata"))
                            ct = dtype or meta.get("data_type") or meta.get("mimeType")
                            if ct and ct not in at.content_types:
                                at.content_types.append(ct)
    except httpx.HTTPStatusError as exc:
        at.status = exc.response.status_code
    except httpx.TransportError:
        at.reason = "transport-error"
    except _MalformedStream:
        at.reason = "malformed-stream"
    if message_seen:
        task_id = cur_state = ""
    at.failed = cur_state in ("failed", "rejected", "canceled")
    if cur_state in ("failed", "rejected"):
        at.error_text = at.reply
    at.ids = {"task_id": task_id, "context_id": ctx_id, "state": cur_state}
    return at


async def _agui_attempt(
    client: httpx.AsyncClient,
    query: str,
    thread_id: str,
    messages: list[dict[str, Any]],
    driver: ChatDriver | None = None,
) -> _Attempt:
    at = _Attempt()
    try:
        driver = driver or await _card_driver(client)
    except httpx.HTTPStatusError as exc:
        return _card_failed(at, exc)
    errors: list[str] = []
    snapshot = list(messages)
    try:
        at.reply = await driver.agui_turn(
            query,
            thread_id,
            messages,
            emit={
                "tool_start": at.tools.append,
                "artifact": lambda dt, _t: at.content_types.append(dt),
                "error": errors.append,
            },
        )
    except httpx.HTTPStatusError as exc:
        at.status = exc.response.status_code
    except httpx.TransportError:
        at.reason = "transport-error"
    if MALFORMED_STREAM_TEXT in errors:
        at.reason = "malformed-stream"
    at.error_text = " ".join(errors)
    at.failed = bool(errors) and not at.reply
    return _restore_if_failed(at, messages, snapshot)


def _restore_if_failed(at: _Attempt, messages: list[dict[str, Any]], snapshot: list[dict[str, Any]]) -> _Attempt:
    if at.classify():
        return at
    messages[:] = snapshot
    return at


def _read_json_list(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def _read(path: Path) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return ""


async def run_turn(
    *,
    transport: str,
    base_url: str,
    key_file: str | Path,
    query: str,
    run_key: str,
    state_dir: str | Path | None = None,
    lock_dir: str | Path | None = None,
    max_slots: int = DEFAULT_SLOTS,
    budget_s: float = DEFAULT_BUDGET_S,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Run one turn with slot limiting and rate-limit retry.

    Returns ``{ok, reply, contentTypes, toolsCalled, attempts}`` on success and
    ``{ok: False, failureClass, reason, status, attempts, ...}`` on failure
    (``failureClass`` is ``"rate-limited"`` when any attempt was rate-limited,
    else ``"turn-failed"``).  A2A task/context ids and the AG-UI message list
    are persisted only after a successful attempt.
    """
    if transport not in ("a2a", "agui"):
        raise ValueError("transport must be 'a2a' or 'agui'")
    budget = min(budget_s, DEFAULT_BUDGET_S)
    deadline = _now() + budget
    sdir = Path(state_dir) if state_dir else Path(tempfile.gettempdir())
    ldir = Path(lock_dir) if lock_dir else Path(tempfile.gettempdir()) / "acc-slots"
    key = _safe(run_key)
    limiter = SlotLimiter(ldir, max_slots)

    owns_client = client is None
    if client is None:
        token = Path(key_file).read_text().strip()
        client = httpx.AsyncClient(
            base_url=base_url, headers={"Authorization": f"Bearer {token}"}, timeout=min(300.0, budget)
        )
    try:
        files = {
            "task": sdir / f"acc-{key}-a2a-task.txt",
            "ctx": sdir / f"acc-{key}-a2a-ctx.txt",
            "state": sdir / f"acc-{key}-a2a-state.txt",
            "msgs": sdir / f"acc-{key}-agui-msgs.json",
        }
        messages = _read_json_list(files["msgs"]) if transport == "agui" else []
        a2a_state = {
            "task_id": _read(files["task"]),
            "context_id": _read(files["ctx"]),
            "state": _read(files["state"]),
        }
        card_driver: ChatDriver | None = None

        async def _run_attempt() -> _Attempt:
            nonlocal card_driver
            if card_driver is None:
                try:
                    card_driver = await _card_driver(client)
                except httpx.HTTPStatusError as exc:
                    return _card_failed(_Attempt(), exc)
            drv = card_driver
            if transport == "a2a":
                return await _a2a_attempt(client, query, a2a_state, drv)
            return await _agui_attempt(client, query, f"{key}-agui", messages, drv)

        attempts = 0
        any_rate_limited = False
        last: _Attempt | None = None
        while True:
            slot = await limiter.acquire(deadline)
            if slot is None:
                last = last or _Attempt()
                last.reason = "slot-wait-exceeded"
                any_rate_limited = True
                break
            snapshot = list(messages)
            try:
                attempts += 1
                try:
                    last = await asyncio.wait_for(_run_attempt(), timeout=max(0.0, deadline - _now()))
                    ok = last.classify() if transport == "a2a" else not last.reason
                except asyncio.TimeoutError:
                    messages[:] = snapshot
                    last = _Attempt()
                    last.reason = "budget-exceeded"
                    break
            finally:
                slot.release()
            any_rate_limited = any_rate_limited or last.rate_limited
            if ok:
                break
            delay = min(_BACKOFF_CAP_S, _BACKOFF_BASE_S * 2 ** (attempts - 1))
            logger.warning(
                "turn retry status=%s attempt=%d reason=%s", last.status, attempts, last.reason
            )
            if _now() + delay > deadline:
                break
            await _sleep(delay)

        if last is not None and not last.reason:
            sdir.mkdir(parents=True, exist_ok=True)
            if transport == "a2a":
                for name, k in (("task", "task_id"), ("ctx", "context_id"), ("state", "state")):
                    value = last.ids.get(k, "")
                    if value or name != "ctx":
                        files[name].write_text(value)
            else:
                files["msgs"].write_text(json.dumps(messages))
            return {
                "ok": True,
                "reply": last.reply,
                "contentTypes": last.content_types,
                "toolsCalled": last.tools,
                "attempts": attempts,
            }
        reason = last.reason if last else "unknown"
        logger.warning("turn failed attempts=%d reason=%s", attempts, reason)
        return {
            "ok": False,
            "failureClass": "rate-limited" if any_rate_limited else "turn-failed",
            "reason": reason,
            "status": last.status if last else None,
            "attempts": attempts,
            "reply": "",
            "contentTypes": [],
            "toolsCalled": [],
        }
    finally:
        if owns_client:
            await client.aclose()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m agent_sdk.testing.turns")
    p.add_argument("--transport", required=True, choices=["a2a", "agui"])
    p.add_argument("--base-url", required=True)
    p.add_argument("--key-file", required=True)
    p.add_argument("--run-key", required=True)
    p.add_argument("--slots", type=int, default=DEFAULT_SLOTS)
    p.add_argument("--lock-dir")
    p.add_argument("--state-dir")
    p.add_argument("--budget", type=float, default=DEFAULT_BUDGET_S)
    ns = p.parse_args(argv)
    query = os.environ.get("ACC_QUERY", "")
    if not query:
        print(json.dumps({"ok": False, "failureClass": "turn-failed", "reason": "no-query"}))
        return 2
    out = asyncio.run(
        run_turn(
            transport=ns.transport, base_url=ns.base_url, key_file=ns.key_file,
            query=query, run_key=ns.run_key, state_dir=ns.state_dir,
            lock_dir=ns.lock_dir, max_slots=ns.slots, budget_s=ns.budget,
        )
    )
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
