"""Test utilities (PROVISIONAL — DESIGN.md §4.0).

``FakeModelClient`` replays scripted ``ModelResponse``s through the real
loop; fixtures construct isolated ``Agent`` instances against it so protocol
behavior is tested end-to-end without Bedrock.

``ChatDriver`` drives live turns against a booted agent over AG-UI or A2A.
Used by ``python -m agent_sdk test-chat`` and available for integration tests.

``run_turn`` (``turns.py``) is a throttled, retrying one-turn helper for acceptance runs.

``McpClient`` / ``run_gate`` (``mcp.py``) drive the acceptance Phase 1.5 MCP tools gate.
"""

from .chat import A2AError, ChatDriver
from .fake_model import FakeModelClient, reply, tool_call

__all__ = ["A2AError", "ChatDriver", "FakeModelClient", "McpClient", "SlotLimiter", "reply", "run_gate", "run_turn", "tool_call"]


def __getattr__(name: str):  # lazy: keeps ``python -m agent_sdk.testing.turns`` warning-free
    if name in ("run_turn", "SlotLimiter"):
        from . import turns

        return getattr(turns, name)
    if name in ("McpClient", "run_gate"):
        from . import mcp

        return getattr(mcp, name)
    raise AttributeError(name)
