"""RT-001 (round 2, GH-143 follow-up) — the per-identity GET /mcp stream cap
must not collapse an entire organization onto one quota.

Root cause: ``_identity_key()`` (routes/mcp.py) is built from
``Identity.subject``, which is an OAuth client_id (auth/oauth_tokens.py:393)
or API-key id (auth/api_keys.py:107) — never an end user. Under this SDK's
own documented org-wide OAuth client mode
(``python -m agent_sdk provision-org-oauth-client``, config.py) or a shared
API key, every caller in the organization collapses onto the SAME identity
key. The old hardcoded ``_MAX_GET_STREAMS_PER_IDENTITY = 8`` therefore capped
the whole org — not one caller — at 8 concurrent MCP connectors.

This module verifies:
- the default per-identity cap is now large enough to admit a realistic
  number of distinct connections sharing one identity (the org-wide
  scenario), not just a single caller's retries.
- ``AGENT_SDK_MAX_MCP_STREAMS_PER_IDENTITY`` (``settings.max_mcp_streams_per_identity``)
  overrides the SDK default live, in both directions.
- the effective cap is never allowed above the process-wide ``_MAX_GET_STREAMS``
  budget, regardless of how high the override is set.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from agent_sdk.routes import mcp as mcp_module
from agent_sdk.routes.mcp import _get_streams, _max_streams_per_identity


async def _still_streaming(task: "asyncio.Task[httpx.Response]", timeout: float = 0.5) -> bool:
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
        return False
    except asyncio.TimeoutError:
        return True


async def _cancel(task: "asyncio.Task[httpx.Response]") -> None:
    if not task.done():
        task.cancel()
    try:
        await task
    except BaseException:
        pass


# ---------------------------------------------------------------------------
# Structural — the setting exists and feeds the resolver
# ---------------------------------------------------------------------------


def test_settings_field_exists_with_documented_alias(settings) -> None:
    assert settings.max_mcp_streams_per_identity is None, (
        "default must be None (fall back to the SDK default), not a baked-in value"
    )


def test_default_effective_cap_is_the_raised_sdk_default(app) -> None:
    """No override configured: the effective cap is the SDK's own raised
    default, not the old org-collapsing value of 8."""
    assert app.state.settings.max_mcp_streams_per_identity is None
    effective = _max_streams_per_identity(app)
    assert effective == mcp_module._MAX_GET_STREAMS_PER_IDENTITY
    assert effective > 8, (
        "the default per-identity cap must be raised well above the old "
        f"org-collapsing value of 8; got {effective}"
    )


def test_override_is_honored_in_both_directions(app, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app.state.settings, "max_mcp_streams_per_identity", 3)
    assert _max_streams_per_identity(app) == 3

    monkeypatch.setattr(app.state.settings, "max_mcp_streams_per_identity", 350)
    assert _max_streams_per_identity(app) == 350


def test_override_is_clamped_to_the_global_cap(
    app, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A per-identity cap above the process-wide budget is meaningless and
    must never let one identity exceed the global stream budget."""
    monkeypatch.setattr(mcp_module, "_MAX_GET_STREAMS", 50)
    monkeypatch.setattr(app.state.settings, "max_mcp_streams_per_identity", 10_000)
    assert _max_streams_per_identity(app) == 50


# ---------------------------------------------------------------------------
# Live — many distinct connections sharing ONE identity (org-wide scenario)
# ---------------------------------------------------------------------------


async def test_many_distinct_connections_sharing_one_identity_all_admit(
    client: httpx.AsyncClient, app
) -> None:
    """Simulates the org-wide OAuth-client / shared-API-key deployment mode:
    N distinct connector processes, all authenticating with the SAME
    identity, opening GET /mcp concurrently. Before this fix the 9th such
    connection was rejected with 429 regardless of org size; now the default
    cap accommodates a realistic number of simultaneous org members."""
    streams = _get_streams(app)
    n = 20
    assert n > 8, "must exceed the old per-identity cap to prove the collapse is fixed"

    tasks = [asyncio.create_task(client.get("/mcp")) for _ in range(n)]
    try:
        for i, t in enumerate(tasks):
            assert await _still_streaming(t), (
                f"connection {i} (of {n}) sharing one identity was rejected — "
                "the org-wide OAuth-client / shared-API-key deployment mode "
                "would be capped far below a realistic org size"
            )
        assert len(streams) == n
    finally:
        for t in tasks:
            await _cancel(t)


async def test_operator_configured_org_size_is_still_enforced(
    client: httpx.AsyncClient, app, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cap is real, not disabled — an operator-configured ceiling still
    rejects once reached, just at a value the operator chose for their org."""
    monkeypatch.setattr(app.state.settings, "max_mcp_streams_per_identity", 2)
    monkeypatch.setattr(mcp_module, "_MAX_GET_STREAMS", 1_000)
    streams = _get_streams(app)

    tasks = [asyncio.create_task(client.get("/mcp")) for _ in range(2)]
    try:
        for t in tasks:
            assert await _still_streaming(t)
        assert len(streams) == 2

        r3 = await asyncio.wait_for(client.get("/mcp"), timeout=5)
        assert r3.status_code == 429, (
            f"3rd stream past the operator's configured cap must still be "
            f"rejected; got {r3.status_code}: {r3.text}"
        )
        assert len(streams) == 2
    finally:
        for t in tasks:
            await _cancel(t)
