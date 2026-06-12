"""Test utilities (PROVISIONAL — DESIGN.md §4.0).

``FakeModelClient`` replays scripted ``ModelResponse``s through the real
loop; fixtures construct isolated ``Agent`` instances against it so protocol
behavior is tested end-to-end without Bedrock.

``ChatDriver`` drives live turns against a booted agent over AG-UI or A2A.
Used by ``python -m agent_sdk test-chat`` and available for integration tests.
"""

from .chat import ChatDriver
from .fake_model import FakeModelClient, reply, tool_call

__all__ = ["ChatDriver", "FakeModelClient", "reply", "tool_call"]
