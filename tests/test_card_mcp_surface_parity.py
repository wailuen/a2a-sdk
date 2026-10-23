"""Parity guard: every skill the agent card advertises must be callable via MCP.

LRN-094: build_agent_card() previously used registry.all() (tier-1 + tier-2)
while MCP tools/list uses registry.tier1() only.  An MCP consumer discovering
a tier-2 skill from the card and calling tools/call would receive -32602
invalid-params — a silent contract violation with no prior hint.

After the fix, build_agent_card() uses registry.tier1(), so card skills and
MCP tools/list are identical sets.
"""

from __future__ import annotations

import json


async def test_card_skills_match_mcp_tools(client):
    """Every skill in the agent card must appear in MCP tools/list."""
    card_r = await client.get("/.well-known/agent-card.json")
    assert card_r.status_code == 200
    card = card_r.json()
    card_skill_ids = {s["id"] for s in card["skills"]}

    # MCP initialize to obtain a session, then tools/list.
    init_r = await client.post(
        "/mcp",
        content=json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "clientInfo": {"name": "test", "version": "0"}, "capabilities": {}}}
        ),
        headers={
            "Content-Type": "application/json",
            "MCP-Protocol-Version": "2025-06-18",
        },
    )
    assert init_r.status_code == 200
    session_id = init_r.headers["mcp-session-id"]

    list_r = await client.post(
        "/mcp",
        content=json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}),
        headers={
            "Content-Type": "application/json",
            "MCP-Protocol-Version": "2025-06-18",
            "Mcp-Session-Id": session_id,
        },
    )
    assert list_r.status_code == 200
    mcp_tool_names = {t["name"] for t in list_r.json()["result"]["tools"]}

    # Every card skill must be callable on MCP — no extras that would produce -32602.
    assert card_skill_ids == mcp_tool_names, (
        f"Card skills not in MCP tools/list: {card_skill_ids - mcp_tool_names}\n"
        f"MCP tools not in card: {mcp_tool_names - card_skill_ids}"
    )
