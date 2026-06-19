"""GH-71: Four protocol bugs in acceptance-api.js generated Python script.

Tests exercise /v1/message:stream (colon path) with flat MessageSendParams
(no JSON-RPC wrapper), a messageId on the message, and SSE event parsing
using ev["kind"] == "status-update" / "artifact-update".

Each test corresponds to one of the four AC bullet points.

Template-content tests (RT-003)
--------------------------------
The SDK-route tests below prove the *target* is correct, but a regression in
the JS template itself (e.g. reverting to /v1/message/stream, dropping
messageId, or switching back to ev["method"]) would pass all SDK tests.
The ``test_template_*`` functions below guard the emitted script string
directly, so a template regression is caught at the source.

Extraction algorithm integration tests (RT-003 gap)
-----------------------------------------------------
``test_extraction_*`` functions execute the exact extraction logic that lives
inside the JS-embedded Python script against a real SSE stream captured from
the test client.  This layer of tests catches bugs in the extraction algorithm
itself (e.g. reply-duplication from collecting both working and final
status-update events) that the template-string and route-shape tests above
cannot detect.

The canonical extraction algorithm is implemented in
``_run_extraction_algorithm`` below, mirroring the embedded Python block in
``harness/workflows/acceptance-api.js``.  Any change to the JS block MUST be
reflected here so the two stay in sync.
"""

from __future__ import annotations

import inspect
import json
import re
import uuid
from pathlib import Path

import pytest

from agent_sdk.testing import reply, tool_call

from .conftest import sse_frames

# ── Template-content guard (RT-003) ────────────────────────────────────────
#
# acceptance-api.js embeds the A2A Python script as a JS string literal inside
# buildScenarioPrompt().  We extract only the lines that make up that embedded
# block (they begin with spaces and a single-quoted Python fragment) so we can
# assert on the four GH-71 invariants without running Node.
#
# The block runs from the first '   import asyncio' line to the
# '   asyncio.run(main())\n' sentinel (inclusive).

_JS_FILE = Path(__file__).parent.parent / "harness" / "workflows" / "acceptance-api.js"


def _extract_a2a_script_block(js_text: str) -> str:
    """Return the Python lines embedded in the A2A section of buildScenarioPrompt."""
    lines = js_text.splitlines()
    in_block = False
    block_lines: list[str] = []
    for line in lines:
        if not in_block:
            if "import asyncio, httpx, json, os" in line:
                in_block = True
                block_lines.append(line)
        else:
            block_lines.append(line)
            if "asyncio.run(main())" in line:
                break
    assert block_lines, "Could not locate the A2A Python script block in acceptance-api.js"
    return "\n".join(block_lines)


@pytest.fixture(scope="module")
def a2a_script_block() -> str:
    js_text = _JS_FILE.read_text(encoding="utf-8")
    return _extract_a2a_script_block(js_text)


def test_template_uses_colon_path(a2a_script_block: str) -> None:
    """/v1/message:stream (colon) must appear in the generated A2A script."""
    assert "/v1/message:stream" in a2a_script_block, (
        "acceptance-api.js A2A script block uses the wrong endpoint path — "
        "expected '/v1/message:stream' (colon), not '/v1/message/stream' (slash)."
    )


def test_template_no_slash_stream_path(a2a_script_block: str) -> None:
    """/v1/message/stream (slash) must NOT appear in the generated A2A script."""
    assert "/v1/message/stream" not in a2a_script_block, (
        "acceptance-api.js A2A script block contains the legacy slash path "
        "'/v1/message/stream' — must use '/v1/message:stream'."
    )


def test_template_message_id_on_message(a2a_script_block: str) -> None:
    """messageId must be set directly on the message dict (not absent)."""
    assert '"messageId"' in a2a_script_block or "'messageId'" in a2a_script_block, (
        "acceptance-api.js A2A script block does not set 'messageId' on the "
        "message — GH-71 AC 3 requires messageId to be present."
    )


def test_template_no_jsonrpc_wrapper(a2a_script_block: str) -> None:
    """The generated script must not wrap the body in a JSON-RPC envelope."""
    assert "jsonrpc" not in a2a_script_block, (
        "acceptance-api.js A2A script block contains a 'jsonrpc' key — "
        "the flat MessageSendParams body must not be JSON-RPC wrapped (GH-71 AC 2)."
    )
    assert '"method"' not in a2a_script_block and "'method'" not in a2a_script_block, (
        "acceptance-api.js A2A script block contains a 'method' key — "
        "the flat body must not include a JSON-RPC 'method' field (GH-71 AC 2)."
    )


def test_template_kind_status_update_parsing(a2a_script_block: str) -> None:
    """ev.get(\"kind\") == \"status-update\" must be present in the A2A script."""
    assert 'ev.get("kind") == "status-update"' in a2a_script_block or (
        "ev.get('kind') == 'status-update'" in a2a_script_block
    ), (
        "acceptance-api.js A2A script block does not parse SSE events using "
        "ev.get('kind') == 'status-update' — GH-71 AC 4 requires kind-based parsing."
    )


def test_template_kind_artifact_update_parsing(a2a_script_block: str) -> None:
    """ev.get(\"kind\") == \"artifact-update\" must be present in the A2A script."""
    assert 'ev.get("kind") == "artifact-update"' in a2a_script_block or (
        "ev.get('kind') == 'artifact-update'" in a2a_script_block
    ), (
        "acceptance-api.js A2A script block does not parse SSE events using "
        "ev.get('kind') == 'artifact-update' — GH-71 AC 4 requires kind-based parsing."
    )


def test_template_no_method_field_parsing(a2a_script_block: str) -> None:
    """The A2A script must not read ev[\"method\"] or ev.get(\"method\") for dispatch."""
    assert 'ev.get("method")' not in a2a_script_block, (
        "acceptance-api.js A2A script block uses ev.get('method') for event "
        "dispatch — must use ev.get('kind') (GH-71 AC 4)."
    )
    assert 'ev["method"]' not in a2a_script_block, (
        "acceptance-api.js A2A script block uses ev['method'] for event "
        "dispatch — must use ev.get('kind') (GH-71 AC 4)."
    )


def test_template_reply_collection_guards_against_duplication(a2a_script_block: str) -> None:
    """The A2A script must guard reply collection with a final/completed check.

    Without this guard the script appends the reply text from every
    status-update event (including intermediate working events), duplicating
    the text that the final completed event already provides in full.
    """
    has_final_guard = 'ev.get("final")' in a2a_script_block or "ev.get('final')" in a2a_script_block
    has_state_guard = '"completed"' in a2a_script_block or "'completed'" in a2a_script_block
    assert has_final_guard or has_state_guard, (
        "acceptance-api.js A2A script block collects reply text from every "
        "status-update event — it must guard with ev.get('final') or a state=completed "
        "check to avoid duplicating the reply (RT-003 extraction algorithm correctness)."
    )


def stream_body(text: str, task_id: str | None = None) -> dict:
    """Flat MessageSendParams — no JSON-RPC envelope, includes messageId."""
    msg: dict = {
        "role": "user",
        "parts": [{"kind": "text", "text": text}],
        "messageId": uuid.uuid4().hex,
    }
    if task_id:
        msg["taskId"] = task_id
    return {"message": msg}


# ── AC 1+2: colon path + flat body ─────────────────────────────────────────

async def test_stream_colon_path_returns_200(client, fake_model):
    """POST /v1/message:stream (colon, not slash) with flat body → 200 SSE."""
    fake_model.script(reply("Hello!"))

    async with client.stream(
        "POST",
        "/v1/message:stream",
        json=stream_body("hi"),
    ) as r:
        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]


async def test_slash_path_is_not_a2a_route(client, fake_model):
    """POST /v1/message/stream (slash) must NOT be the streaming endpoint.

    With the slash URL the server should return 404 or 405 — not 200.
    This test pins that the colon is not interchangeable.
    """
    fake_model.script(reply("Hello!"))

    r = await client.post(
        "/v1/message/stream",
        json=stream_body("hi"),
    )
    assert r.status_code in (404, 405)


async def test_jsonrpc_envelope_rejected_as_invalid_params(client, fake_model):
    """Wrapping the body in a JSON-RPC envelope causes -32602.

    The endpoint expects flat MessageSendParams; a JSON-RPC object is not
    a valid MessageSendParams and the server must return -32602.
    """
    fake_model.script(reply("Hello!"))

    r = await client.post(
        "/v1/message:stream",
        json={
            "jsonrpc": "2.0",
            "method": "message/stream",
            "id": "test-1",
            "params": stream_body("hi"),
        },
    )
    assert r.status_code in (400, 422)
    body = r.json()
    assert body.get("error", {}).get("code") == -32602


# ── AC 3: messageId required ────────────────────────────────────────────────

async def test_missing_message_id_returns_invalid_params_on_stream(client, fake_model):
    """Omitting messageId on /v1/message:stream must return -32602."""
    fake_model.script(reply("Hello!"))

    r = await client.post(
        "/v1/message:stream",
        json={"message": {"role": "user", "parts": [{"kind": "text", "text": "hi"}]}},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == -32602


async def test_with_message_id_stream_succeeds(client, fake_model):
    """Including messageId succeeds and produces SSE frames."""
    fake_model.script(reply("Done."))

    chunks: list[bytes] = []
    async with client.stream(
        "POST",
        "/v1/message:stream",
        json=stream_body("hello with message id"),
    ) as r:
        assert r.status_code == 200
        async for chunk in r.aiter_bytes():
            chunks.append(chunk)

    raw = b"".join(chunks).decode()
    frames = sse_frames(raw)
    assert len(frames) >= 1


# ── AC 4: SSE event kind field ──────────────────────────────────────────────

async def test_sse_events_use_kind_not_method(client, fake_model):
    """SSE events carry ``kind`` (not ``method``) — must be status-update / artifact-update."""
    fake_model.script(reply("Done."))

    chunks: list[bytes] = []
    async with client.stream(
        "POST",
        "/v1/message:stream",
        json=stream_body("parse events"),
    ) as r:
        assert r.status_code == 200
        async for chunk in r.aiter_bytes():
            chunks.append(chunk)

    raw = b"".join(chunks).decode()
    frames = sse_frames(raw)
    assert len(frames) >= 1

    kinds = {f.get("kind") for f in frames}
    # must not use old-style method names
    assert "taskStatusUpdated" not in kinds
    assert "taskArtifactUpdated" not in kinds
    # at least one frame must be a recognised kind
    recognised = {"task", "status-update", "artifact-update"}
    assert kinds & recognised, f"no recognised kind in {kinds}"


async def test_status_update_event_shape(client, fake_model):
    """status-update events carry taskId, contextId, status — not params wrapper."""
    fake_model.script(reply("Done."))

    chunks: list[bytes] = []
    async with client.stream(
        "POST",
        "/v1/message:stream",
        json=stream_body("shape check"),
    ) as r:
        assert r.status_code == 200
        async for chunk in r.aiter_bytes():
            chunks.append(chunk)

    raw = b"".join(chunks).decode()
    frames = sse_frames(raw)

    status_events = [f for f in frames if f.get("kind") == "status-update"]
    assert status_events, f"no status-update events; got: {[f.get('kind') for f in frames]}"

    for ev in status_events:
        # AC 4: payload is directly on ev, not under ev["params"]
        assert "taskId" in ev, "taskId missing from status-update event"
        assert "contextId" in ev, "contextId missing from status-update event"
        assert "status" in ev, "status missing from status-update event"
        # must not be the old JSON-RPC params-wrapped shape
        assert "params" not in ev, "status-update event must not have a 'params' wrapper"
        assert "method" not in ev, "status-update event must not have a 'method' field"


async def test_artifact_update_event_shape(client, fake_model):
    """artifact-update events carry artifact directly on the event (not under params)."""
    fake_model.script(
        tool_call("demo_kpis", {"title": "Q2"}), reply("KPIs attached.")
    )

    from agent_sdk.models.content_types import A2UI_EXTENSION_URI

    chunks: list[bytes] = []
    async with client.stream(
        "POST",
        "/v1/message:stream",
        json=stream_body("kpis please"),
        headers={"X-A2A-Extensions": A2UI_EXTENSION_URI},
    ) as r:
        assert r.status_code == 200
        async for chunk in r.aiter_bytes():
            chunks.append(chunk)

    raw = b"".join(chunks).decode()
    frames = sse_frames(raw)

    artifact_events = [f for f in frames if f.get("kind") == "artifact-update"]
    assert artifact_events, (
        f"no artifact-update events; got kinds: {[f.get('kind') for f in frames]}"
    )

    for ev in artifact_events:
        # AC 4: artifact is directly on ev, not under ev["params"]
        assert "artifact" in ev, "artifact missing from artifact-update event"
        assert "taskId" in ev, "taskId missing from artifact-update event"
        assert "params" not in ev, "artifact-update must not have a 'params' wrapper"
        assert "method" not in ev, "artifact-update must not have a 'method' field"


# ── AC 5: extraction algorithm integration (RT-003) ────────────────────────
#
# Replicate the embedded Python extraction block from acceptance-api.js and
# run it against real SSE frames from the test client.  Any change to the JS
# block MUST be reflected in ``_run_extraction_algorithm`` to keep the two in
# sync.


def _run_extraction_algorithm(raw_sse: str) -> tuple[str, list[str]]:
    """Execute the A2A extraction algorithm from the acceptance-api.js block.

    Returns ``(reply_text, content_types)`` identical to the embedded script's
    ``{"reply": ..., "contentTypes": ...}`` JSON output.

    Algorithm mirrors lines 127–151 of harness/workflows/acceptance-api.js.
    The key correctness rule: collect reply text ONLY from the final or
    completed status-update so that intermediate working status-updates —
    which each carry only the most-recent text segment — do not duplicate the
    complete reply that the final event provides.
    """
    reply_parts: list[str] = []
    ctypes: list[str] = []
    task_id: str | None = None

    for line in raw_sse.splitlines():
        if not line.startswith("data:"):
            continue
        ev = json.loads(line[len("data:"):].strip())
        kind = ev.get("kind")
        if kind == "task":
            if not task_id:
                task_id = ev.get("id", "")
        elif kind == "status-update":
            if not task_id:
                task_id = ev.get("taskId", "")
            # Collect reply text only from the final/completed event.
            # Intermediate working status-updates each carry only one text
            # segment; the final completed event joins all segments into the
            # complete reply.  Collecting from every event causes duplication.
            # Mirrors: if ev.get("final") or ev.get("status",{}).get("state") == "completed"
            if ev.get("final") or (ev.get("status", {}).get("state") == "completed"):
                reply_parts = [
                    p["text"]
                    for p in (ev.get("status", {}).get("message") or {}).get("parts", [])
                    if p.get("kind") == "text"
                ]
        elif kind == "artifact-update":
            art = ev.get("artifact") or {}
            art_meta = art.get("metadata") or {}
            art_dtype = art_meta.get("data_type") or art.get("name")
            for part in art.get("parts", []):
                if part.get("kind") == "data":
                    meta = part.get("metadata") or {}
                    ctype = art_dtype or meta.get("data_type") or meta.get("mimeType")
                    if ctype and ctype not in ctypes:
                        ctypes.append(ctype)

    return "\n".join(reply_parts), ctypes


async def test_extraction_algorithm_no_reply_duplication(client, fake_model):
    """Extraction algorithm must not duplicate the reply across status-update events.

    The SDK emits one working status-update per text segment AND a final
    completed status-update that joins all segments.  Collecting text from
    every status-update doubles the reply.  The algorithm must collect only
    from the final event.
    """
    fake_model.script(reply("Hello extraction!"))

    chunks: list[bytes] = []
    async with client.stream(
        "POST",
        "/v1/message:stream",
        json=stream_body("run extraction test"),
    ) as r:
        assert r.status_code == 200
        async for chunk in r.aiter_bytes():
            chunks.append(chunk)

    raw = b"".join(chunks).decode()
    extracted_reply, _ = _run_extraction_algorithm(raw)

    assert extracted_reply == "Hello extraction!", (
        f"Extraction algorithm duplicated the reply: {extracted_reply!r}. "
        "Check that text is only collected from the final status-update event."
    )


async def test_extraction_algorithm_content_types_from_artifact(client, fake_model):
    """Extraction algorithm must collect content types from artifact-update events.

    For a KpiCard artifact the algorithm must surface ``'kpi_card'`` (the
    ``data_type`` field on the artifact metadata) in the returned content-types
    list, and must not surface it more than once.
    """
    from agent_sdk.models.content_types import A2UI_EXTENSION_URI

    fake_model.script(tool_call("demo_kpis", {"title": "Q2"}), reply("KPIs attached."))

    chunks: list[bytes] = []
    async with client.stream(
        "POST",
        "/v1/message:stream",
        json=stream_body("show kpis"),
        headers={"X-A2A-Extensions": A2UI_EXTENSION_URI},
    ) as r:
        assert r.status_code == 200
        async for chunk in r.aiter_bytes():
            chunks.append(chunk)

    raw = b"".join(chunks).decode()
    extracted_reply, ctypes = _run_extraction_algorithm(raw)

    assert "kpi_card" in ctypes, (
        f"Extraction algorithm did not find 'kpi_card' in content types: {ctypes!r}. "
        "Check that art_dtype is read from artifact.metadata.data_type."
    )
    assert ctypes.count("kpi_card") == 1, (
        f"'kpi_card' appears {ctypes.count('kpi_card')} times in {ctypes!r} — must appear exactly once."
    )
    assert extracted_reply == "KPIs attached.", (
        f"Extraction algorithm produced wrong reply: {extracted_reply!r}"
    )


# ── Mirror drift guard (RT-002) ────────────────────────────────────────────
#
# ``_run_extraction_algorithm`` is a hand-maintained copy of the embedded
# Python block in acceptance-api.js.  The "Any change to the JS block MUST be
# reflected here" comment is not self-enforcing — a future edit to the JS
# extraction logic that the mirror does not track would leave the integration
# tests above passing against stale logic (LRN-065/LRN-066 silent divergence).
#
# This guard makes the sync requirement mechanical: the two load-bearing
# correctness invariants — (1) reply text collected ONLY from the final/
# completed status-update, and (2) art_dtype derived from the artifact
# metadata data_type with a fallback to the artifact name — must appear in BOTH
# the JS-embedded block and the mirror's source.  Editing one without the other
# fails this test.

# (canonical_substring_in_js, canonical_substring_in_mirror) per invariant.
# The JS block writes one statement per single-quoted fragment with leading
# whitespace; the substrings below are the whitespace-collapsed core of each
# invariant so the guard is robust to indentation but strict on logic.
_EXTRACTION_INVARIANTS = (
    # (1) final / completed reply guard
    (
        'if ev.get("final") or (ev.get("status",{}).get("state") == "completed"):',
        'if ev.get("final") or (ev.get("status", {}).get("state") == "completed"):',
    ),
    # (2) art_dtype = metadata.data_type or name
    (
        'art_dtype = art_meta.get("data_type") or art_name',
        'art_dtype = art_meta.get("data_type") or art.get("name")',
    ),
)


def _collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def test_extraction_mirror_matches_js_block(a2a_script_block: str) -> None:
    """The hand-maintained mirror must track the JS-embedded extraction block.

    Guards the two load-bearing extraction invariants in both the JS source of
    truth and ``_run_extraction_algorithm``.  If the JS block is edited (e.g.
    the final/completed reply guard or the art_dtype derivation changes) without
    updating the mirror, this fails — so the integration tests above can never
    pass against stale mirror logic (RT-002 / LRN-065 / LRN-066)."""
    js_norm = _collapse_ws(a2a_script_block)
    mirror_norm = _collapse_ws(inspect.getsource(_run_extraction_algorithm))

    for js_core, mirror_core in _EXTRACTION_INVARIANTS:
        assert _collapse_ws(js_core) in js_norm, (
            "acceptance-api.js A2A extraction block no longer contains the "
            f"invariant {js_core!r}. If the JS logic changed intentionally, "
            "update both the JS block AND _run_extraction_algorithm, then update "
            "this guard's _EXTRACTION_INVARIANTS."
        )
        assert _collapse_ws(mirror_core) in mirror_norm, (
            "_run_extraction_algorithm no longer contains the invariant "
            f"{mirror_core!r} — the mirror has drifted from the JS block "
            "(RT-002). Re-sync the mirror with the embedded JS extraction logic."
        )
