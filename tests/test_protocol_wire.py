"""HTTP wire-level protocol conformance tests for GH #4–#8.

These tests describe the CORRECT post-fix behaviour. They target the fixed
state expected after wave W6 lands. Do not skip or xfail them.

Groups:
  1. CORS expose-headers on preflight (GH #8)
  2. WWW-Authenticate resource_metadata on 401 (GH #7)
  3. MCP-Protocol-Version header / body agreement on initialize (GH #4)
  4. Agent card customEvents shape (GH #5)
  5. build_artifact DataPart / A2UI gating (GH #6)
  6. DataPart.data inbound/construction narrowing (GH-128): model-level
     rejection of a bare-array data field plus the end-to-end -32602
     rejection via POST /v1/message:send.
  7. FilePart.file bytes-XOR-uri validation (L-5)
  8. Bedrock admin-credential HTTP seam (RT-001 / GH-72)

Most groups' HTTP tests use the shared async httpx client from conftest
(asyncio_mode=auto). Group 5 is a pure unit test of build_artifact(); Group 6
mixes a pure DataPart unit test with one end-to-end -32602 HTTP integration
test; Group 7 is pure unit tests.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _send_body(text: str) -> dict:
    return {
        "message": {
            "role": "user",
            "parts": [{"kind": "text", "text": text}],
            "messageId": uuid.uuid4().hex,
        }
    }


# ===========================================================================
# Group 1 — CORS expose-headers (GH #8)
# ===========================================================================


async def test_cors_preflight_a2a_route_includes_expose_headers(client):
    """OPTIONS preflight to the A2A route must return 204 and expose
    WWW-Authenticate so browsers can start OAuth discovery (GH #8).

    Covers the A2A surface (/v1/message:send); the MCP surface is covered
    by test_protocol_fixes_w6.py::test_cors_preflight_includes_expose_headers."""
    r = await client.options(
        "/v1/message:send",
        headers={
            "Origin": "https://claude.ai",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert r.status_code == 204
    expose = r.headers.get("access-control-expose-headers", "")
    assert "WWW-Authenticate" in expose or "www-authenticate" in expose.lower(), (
        f"access-control-expose-headers missing WWW-Authenticate; got: {expose!r}"
    )


async def test_cors_non_preflight_includes_expose_headers(client):
    """Non-preflight GET with Origin must also carry expose headers (regression
    guard — this worked pre-0.4.0 and must not regress)."""
    r = await client.get(
        "/.well-known/agent.json",
        headers={"Origin": "https://claude.ai"},
    )
    expose = r.headers.get("access-control-expose-headers", "")
    assert "WWW-Authenticate" in expose or "www-authenticate" in expose.lower(), (
        f"access-control-expose-headers missing WWW-Authenticate on non-preflight; got: {expose!r}"
    )


# ===========================================================================
# Group 2 — WWW-Authenticate resource_metadata (GH #7)
# ===========================================================================


async def test_a2a_401_includes_resource_metadata(client):
    """POST /v1/message:send with no Authorization must yield 401 with a
    resource_metadata= WWW-Authenticate challenge (GH #7).

    Before the fix, the A2A surface returned 'Bearer realm=...' instead of
    the PRM-pointing challenge that enables OAuth discovery."""
    r = await client.post(
        "/v1/message:send",
        json=_send_body("hello"),
        headers={"Authorization": ""},  # strip the pre-set admin bearer
    )
    assert r.status_code == 401
    www_auth = r.headers.get("www-authenticate", "")
    assert www_auth.startswith("Bearer resource_metadata="), (
        f"Expected 'Bearer resource_metadata=...' but got: {www_auth!r}"
    )


async def test_agui_401_includes_resource_metadata(client):
    """POST /ag-ui/run (or an admin endpoint) with no auth must also carry
    resource_metadata= in its WWW-Authenticate challenge (GH #7)."""
    # /ag-ui/run is the AG-UI endpoint; fall back to /admin/api/credentials/test
    # if the path varies, but any authenticated-only endpoint is sufficient.
    r = await client.post(
        "/ag-ui/run",
        json={"thread_id": "t1", "run_id": "r1", "messages": []},
        headers={"Authorization": ""},
    )
    # 401 or 422 (missing required fields) are both acceptable; we only care
    # about 401 paths here.  If the server returns 422 the endpoint accepted
    # the request shape, which means auth passed — skip the challenge check.
    if r.status_code == 401:
        www_auth = r.headers.get("www-authenticate", "")
        assert "resource_metadata=" in www_auth, (
            f"AG-UI 401 missing resource_metadata= in WWW-Authenticate; got: {www_auth!r}"
        )
    # 422 means the route exists and auth passed (bearer from fixture) — pass.
    # Any other 4xx/5xx is unexpected; let assertion errors surface naturally.


# ===========================================================================
# Group 3 — MCP-Protocol-Version header / body agreement (GH #4)
# ===========================================================================


async def test_mcp_initialize_version_header_matches_body(client):
    """POST /mcp initialize with protocolVersion 2025-06-18 and no version
    header must echo the negotiated version in BOTH the response header and
    the JSON body (GH #4).

    The bug: the response header carried the server default (2025-03-26) while
    the body echoed the client-requested 2025-06-18.  Both must agree after W6."""
    r = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        },
        # Deliberately omit MCP-Protocol-Version request header —
        # server must still echo the negotiated version in both places.
    )
    assert r.status_code == 200, r.text
    header_version = r.headers.get("mcp-protocol-version")
    assert header_version is not None, "mcp-protocol-version response header missing"
    body = r.json()
    assert "result" in body, f"Expected result in body, got: {body}"
    body_version = body["result"].get("protocolVersion")
    assert body_version == "2025-06-18", (
        f"Body protocolVersion should be 2025-06-18; got {body_version!r}"
    )
    assert header_version == "2025-06-18", (
        f"MCP-Protocol-Version header should be 2025-06-18; got {header_version!r}"
    )
    assert header_version == body_version, (
        f"Header ({header_version!r}) and body ({body_version!r}) protocolVersion disagree"
    )


# ===========================================================================
# Group 4 — Agent card customEvents shape (GH #5)
# ===========================================================================


async def test_agent_card_custom_events_have_value_schema(client):
    """/.well-known/agent.json must advertise customEvents as a list of dicts
    each with 'name' and 'valueSchema', and must include AGENT_ARTIFACT (GH #5).

    The bug: customEvents was a bare list of strings instead of the required
    [{name, valueSchema}] shape."""
    r = await client.get("/.well-known/agent.json")
    assert r.status_code == 200, r.text
    card = r.json()

    x_agui = card.get("x-agui")
    assert x_agui is not None, "Agent card missing x-agui extension"

    custom_events = x_agui.get("customEvents")
    assert isinstance(custom_events, list), (
        f"customEvents must be a list; got {type(custom_events).__name__}"
    )
    assert len(custom_events) > 0, "customEvents must not be empty"

    for entry in custom_events:
        assert isinstance(entry, dict), (
            f"Each customEvents element must be a dict; got {type(entry).__name__}: {entry!r}"
        )
        assert "name" in entry, f"customEvents entry missing 'name': {entry!r}"
        assert "valueSchema" in entry, f"customEvents entry missing 'valueSchema': {entry!r}"

    names = [e["name"] for e in custom_events]
    assert "AGENT_ARTIFACT" in names, (
        f"AGENT_ARTIFACT not found in customEvents names: {names}"
    )


# ===========================================================================
# Group 5 — build_artifact DataPart / A2UI gating (GH #6)
# ===========================================================================


def test_build_artifact_a2ui_disabled_yields_text_and_data_part():
    """When the client capability does not allow the ContentModel type,
    build_artifact must return TextPart + DataPart (plain model dump) —
    P6-02 / GH #6: plain A2A clients always get the structured payload.

    Gating mechanics: Extended-profile types (extended=True) require
    tier="core+extended". With tier="core" only, allows() returns False and
    the translator returns None → TextPart + raw DataPart (not A2UI DataPart)."""
    from agent_sdk.a2ui.translator import A2uiCapabilities
    from agent_sdk.agent.events import ArtifactEvent
    from agent_sdk.agent.runner import build_artifact
    from agent_sdk.models.a2a import DataPart, TextPart
    from agent_sdk.models.content_types import WaterfallChart, WaterfallSegment

    # WaterfallChart has extended=True → requires tier="core+extended"
    payload = WaterfallChart(
        title="Test Waterfall",
        segments=[
            WaterfallSegment(label="Start", value=100.0, type="initial", cumulative=100.0),
            WaterfallSegment(label="End", value=-20.0, type="loss", cumulative=80.0),
        ],
    )
    event = ArtifactEvent(
        data_type="waterfall_chart",
        tool_name="demo_waterfall",
        model=payload,
    )
    # tier="core" → extended=False → allows(WaterfallChart) returns False
    caps_off = A2uiCapabilities(tier="core")

    artifact = build_artifact(event, caps_off)
    # P6-02: must now emit 2 parts even when A2UI is gated off.
    assert len(artifact.parts) == 2, (
        f"Expected 2 parts (TextPart + raw DataPart) when A2UI gated off; got {len(artifact.parts)}"
    )
    assert isinstance(artifact.parts[0], TextPart), (
        f"Expected TextPart as first part; got {type(artifact.parts[0]).__name__}"
    )
    assert isinstance(artifact.parts[1], DataPart), (
        f"Expected DataPart as second part; got {type(artifact.parts[1]).__name__}"
    )
    # DataPart.data is the raw model dump, not an A2UI message array.
    assert isinstance(artifact.parts[1].data, dict), (
        "DataPart.data must be a dict (model dump) when A2UI is gated off"
    )
    meta = artifact.parts[1].metadata or {}
    assert meta.get("data_type") == "waterfall_chart"
    assert meta.get("tool_name") == "demo_waterfall"
    # Must NOT carry the A2UI mimeType (that would confuse A2UI-unaware clients).
    assert meta.get("mimeType") is None, (
        "gated-off DataPart must not carry the A2UI mimeType"
    )


def test_build_artifact_a2ui_enabled_yields_datapart_with_a2ui_mime():
    """When the client capability allows the ContentModel type, build_artifact
    must return [TextPart, DataPart(open), DataPart(close)] — deleteSurface is
    delivered as its own array, never bundled with create/populate (critical
    protocol-conformance fix; see split_a2ui_delivery()) — where each DataPart
    carries the A2UI MIME type (GH #6)."""
    from agent_sdk.a2ui.translator import A2uiCapabilities
    from agent_sdk.agent.events import ArtifactEvent
    from agent_sdk.agent.runner import build_artifact
    from agent_sdk.models.a2a import DataPart, TextPart
    from agent_sdk.models.content_types import A2UI_MIME_TYPE, KpiCard, MetricItem

    payload = KpiCard(
        title="Test KPIs",
        metrics=[MetricItem(label="Revenue", value="$1M", trend="up")],
    )
    event = ArtifactEvent(
        data_type="kpi_card",
        tool_name="demo_kpis",
        model=payload,
    )
    # Standard catalog + core tier → allows() returns True for KpiCard (core, non-extended)
    caps_on = A2uiCapabilities(tier="core")

    artifact = build_artifact(event, caps_on)
    assert len(artifact.parts) == 3, (
        f"Expected 3 parts [TextPart, DataPart, DataPart] when A2UI enabled; "
        f"got {len(artifact.parts)}"
    )
    assert isinstance(artifact.parts[0], TextPart), (
        f"First part must be TextPart; got {type(artifact.parts[0]).__name__}"
    )
    open_part, close_part = artifact.parts[1], artifact.parts[2]
    for data_part in (open_part, close_part):
        assert isinstance(data_part, DataPart), (
            f"Part must be DataPart; got {type(data_part).__name__}"
        )
        part_mime = (data_part.metadata or {}).get("mimeType")
        assert part_mime == A2UI_MIME_TYPE, (
            f"DataPart metadata.mimeType must be {A2UI_MIME_TYPE!r}; got {part_mime!r}"
        )
        # DataPart.data must be an object wrapping the A2UI message array
        # under "messages" — matching the AG-UI CUSTOM value convention (GH-128).
        assert isinstance(data_part.data, dict), (
            f"DataPart.data must be a dict wrapping 'messages'; got {type(data_part.data).__name__}"
        )
        assert isinstance(data_part.data["messages"], list), (
            f"DataPart.data['messages'] must be a list (A2UI message array); "
            f"got {type(data_part.data['messages']).__name__}"
        )
    assert len(open_part.data["messages"]) == 3, (
        f"open DataPart must carry createSurface/updateComponents/updateDataModel; "
        f"got {len(open_part.data['messages'])}"
    )
    assert all("deleteSurface" not in m for m in open_part.data["messages"])
    assert (
        len(close_part.data["messages"]) == 1
        and "deleteSurface" in close_part.data["messages"][0]
    ), "close DataPart must carry exactly the deleteSurface message"


# ===========================================================================
# Group 6 — DataPart.data inbound/construction narrowing (GH-128)
# ===========================================================================


def test_data_part_rejects_bare_array_at_construction():
    """DataPart.data is dict[str, Any] — a bare array (the pre-fix wire shape
    this module used to emit) must fail Pydantic validation at construction
    time, not merely be absent from the wire (RT-002 regression guard)."""
    from agent_sdk.models.a2a import DataPart

    with pytest.raises(ValidationError):
        DataPart(kind="data", data=[{"version": "v0.9.1"}])


async def test_inbound_data_part_bare_array_rejected_as_invalid_params(client):
    """RT-003: the DataPart.data narrowing (dict[str, Any], was
    dict[str, Any] | list[Any]) is symmetric — it also tightens INBOUND
    parsing, not just the outbound A2UI wire shape. A Message.parts DataPart
    whose data is a bare array (the exact shape A2UI v0.9.1's own A2A
    binding mandates for an inbound action DataPart) now fails Pydantic
    validation and is rejected as -32602 (Invalid Params) rather than
    silently coerced. Pins the CURRENT behavior; if inbound A2UI actions
    are ever supported, they must be parsed through a bare-array-tolerant
    path, not this tightened DataPart model (see CHANGELOG 0.5.44)."""
    r = await client.post(
        "/v1/message:send",
        json={
            "message": {
                "role": "user",
                "parts": [{"kind": "data", "data": [{"version": "v0.9.1"}]}],
                "messageId": uuid.uuid4().hex,
            }
        },
    )
    assert r.status_code == 400
    body = r.json()
    assert body["error"]["code"] == -32602, (
        f"expected -32602 Invalid Params, got {body['error']['code']}"
    )


# ===========================================================================
# Group 7 — FilePart.file XOR validation (L-5)
# ===========================================================================


def test_file_part_neither_bytes_nor_uri_raises():
    """FilePart with an empty file dict (neither bytes nor uri) must be rejected
    by the _file_xor validator."""
    from agent_sdk.models.a2a import FilePart

    with pytest.raises(ValidationError):
        FilePart(kind="file", file={})


def test_file_part_bytes_only_is_valid():
    """FilePart with only bytes in the file dict must be accepted."""
    from agent_sdk.models.a2a import FilePart

    part = FilePart(kind="file", file={"bytes": "aGVsbG8="})
    assert part.file.bytes == "aGVsbG8="  # type: ignore[union-attr]


def test_file_part_uri_only_is_valid():
    """FilePart with only uri in the file dict must be accepted."""
    from agent_sdk.models.a2a import FilePart

    part = FilePart(kind="file", file={"uri": "https://example.com/file.pdf"})
    assert part.file.uri == "https://example.com/file.pdf"  # type: ignore[union-attr]


def test_file_part_both_bytes_and_uri_raises():
    """FilePart with both bytes and uri present must be rejected by the _file_xor
    validator."""
    from agent_sdk.models.a2a import FilePart

    with pytest.raises(ValidationError):
        FilePart(kind="file", file={"bytes": "aGVsbG8=", "uri": "https://example.com/file.pdf"})


# ===========================================================================
# Group 8 — Bedrock admin-credential HTTP seam (RT-001 / GH-72)
# ===========================================================================
#
# GH-72 added the aws_session_token Bedrock CredentialField, but the only
# operator-reachable path to seed it — PUT /admin/api/credentials/__bedrock__/
# aws_session_token through _resolve_credential_field → set_credential → store
# — was unverified.  Backend-layer tests (test_bedrock_credential_store.py)
# stop at BedrockModelClient / _build_model_client.  A typo in _BEDROCK_FIELDS,
# an _resolve_credential_field regression, or the field.secret flag drifting
# would pass the whole GH-72 set silently (LRN-077/LRN-078: wire-up/UI changes
# need an integration test at the seam they add).


async def test_admin_put_bedrock_session_token_round_trips(client):
    """PUT to the Bedrock session-token field must store the value and the
    credential store must round-trip it under (NS_BEDROCK, aws_session_token)."""
    from agent_sdk.credentials.store import NS_BEDROCK

    token = "FwoGZXIvYXdzEXAMPLEsessiontoken"
    r = await client.put(
        "/admin/api/credentials/__bedrock__/aws_session_token",
        json={"value": token},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"source": "__bedrock__", "field": "aws_session_token", "set": True}

    store = client.app.state.credential_store  # type: ignore[attr-defined]
    assert store.get(NS_BEDROCK, "aws_session_token") == token, (
        "PUT /admin/api/credentials/__bedrock__/aws_session_token did not "
        "round-trip into the credential store"
    )


async def test_admin_get_bedrock_credentials_lists_session_token(client):
    """The credentials listing must surface aws_session_token as a Bedrock
    field marked secret (the field the admin form renders)."""
    r = await client.get("/admin/api/credentials")
    assert r.status_code == 200, r.text
    bedrock = r.json()["bedrock"]
    assert bedrock["source_name"] == "__bedrock__"
    by_name = {f["name"]: f for f in bedrock["fields"]}
    assert "aws_session_token" in by_name, (
        f"aws_session_token missing from Bedrock fields: {sorted(by_name)}"
    )
    assert by_name["aws_session_token"]["secret"] is True, (
        "aws_session_token must be marked secret=True (it is an STS credential)"
    )


async def test_admin_put_unknown_bedrock_field_returns_404(client):
    """PUT to an unknown __bedrock__ field must 404 (negative-path guard for
    _resolve_credential_field — a field-name typo must not silently 200)."""
    r = await client.put(
        "/admin/api/credentials/__bedrock__/not_a_real_field",
        json={"value": "x"},
    )
    assert r.status_code == 404, r.text


async def test_admin_delete_bedrock_session_token(client):
    """DELETE through the same seam must clear a previously-set session token."""
    from agent_sdk.credentials.store import NS_BEDROCK

    store = client.app.state.credential_store  # type: ignore[attr-defined]
    store.set(NS_BEDROCK, "aws_session_token", "FwoGZXIvYXdzEXAMPLE")

    r = await client.delete("/admin/api/credentials/__bedrock__/aws_session_token")
    assert r.status_code == 200, r.text
    assert r.json() == {"source": "__bedrock__", "field": "aws_session_token", "set": False}
    assert store.get(NS_BEDROCK, "aws_session_token") is None


async def test_admin_put_bedrock_session_token_requires_admin(client):
    """The seam must enforce admin auth (SI: must not widen to bypass auth).
    A request with the admin bearer stripped must be rejected (401/403)."""
    r = await client.put(
        "/admin/api/credentials/__bedrock__/aws_session_token",
        json={"value": "FwoGZXIvYXdzEXAMPLE"},
        headers={"Authorization": ""},
    )
    assert r.status_code in (401, 403), r.text
