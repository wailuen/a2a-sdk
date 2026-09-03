"""RT-B-202 / LRN-144: lock the transcript-bridge centralisation invariant
as a runnable check, not only a description in the LRN file.

LRN-144's Check (workspace/learning/LRN-144-transcript-bridge-must-cover-out-of-loop-writers.md)
splits the invariant into two enumerated concerns:

- Out-of-loop repair writers reach ``bridge_trailing_user`` (agent/loop.py)
  through exactly ONE call site: inside ``agent/runner.py::repair_dangling_tool_use``.
- ``routes/a2a.py``'s ``_create_task_record`` needs the same never-ends-on-
  ``user`` guarantee on the transcript ``TaskStore.context_messages()``
  returns (a read, not a loop exit), but must never call
  ``bridge_trailing_user`` directly — it routes through the thin
  ``agent/loop.py::bridge_context_messages`` wrapper instead, so
  ``routes/a2a.py`` stays at zero direct calls to the bridge itself.
"""

from __future__ import annotations

import re
from pathlib import Path

from agent_sdk.agent.loop import bridge_context_messages

REPO_ROOT = Path(__file__).resolve().parents[1]
A2A_ROUTE = REPO_ROOT / "agent_sdk" / "routes" / "a2a.py"
RUNNER = REPO_ROOT / "agent_sdk" / "agent" / "runner.py"


def _read(path: Path) -> str:
    assert path.exists(), f"file not found: {path}"
    return path.read_text()


def test_a2a_route_never_names_bridge_trailing_user() -> None:
    """LRN-144 Check, bullet 2: ``grep -n "bridge_trailing_user"
    agent_sdk/routes/a2a.py`` must show zero matches — not even in a
    comment, so the grep itself (as documented in the LRN) stays accurate."""
    text = _read(A2A_ROUTE)
    assert "bridge_trailing_user" not in text, (
        "routes/a2a.py must reach the transcript bridge only through "
        "agent/loop.py::bridge_context_messages, never bridge_trailing_user directly"
    )


def test_a2a_route_calls_bridge_context_messages_exactly_once() -> None:
    text = _read(A2A_ROUTE)
    calls = len(re.findall(r"\bbridge_context_messages\(", text))
    assert calls == 1, (
        f"expected exactly one bridge_context_messages(...) call site in "
        f"routes/a2a.py (_create_task_record), found {calls}"
    )


def test_runner_bridge_trailing_user_has_exactly_one_call_site() -> None:
    """LRN-144 Check, bullet 1: the raw bridge is invoked exactly once in
    runner.py — inside repair_dangling_tool_use — everywhere else it is
    only imported or mentioned in a docstring/comment."""
    text = _read(RUNNER)
    calls = len(re.findall(r"\bbridge_trailing_user\(", text))
    assert calls == 1, (
        f"expected exactly one bridge_trailing_user(...) invocation in "
        f"agent/runner.py, found {calls}"
    )


def test_runner_public_repair_dangling_tool_use_safe_symbol_exists() -> None:
    """LRN-144's Check names the guard function `repair_dangling_tool_use_safe`
    (public, no leading underscore) — pin the symbol so the Check's grep
    target cannot silently go stale again (RT-B-202 found it drifted to a
    nonexistent `_repair_dangling_tool_use_safe`)."""
    text = _read(RUNNER)
    assert "def repair_dangling_tool_use_safe(" in text
    assert "_repair_dangling_tool_use_safe" not in text


def test_bridge_context_messages_bridges_a_trailing_user_transcript() -> None:
    prior = [{"role": "user", "content": [{"text": "orphaned prior turn"}]}]
    bridged = bridge_context_messages(prior)
    assert bridged[-1]["role"] == "assistant"
    assert bridged[:-1] == prior


def test_bridge_context_messages_does_not_mutate_its_input() -> None:
    prior = [{"role": "user", "content": [{"text": "orphaned prior turn"}]}]
    original_len = len(prior)
    bridge_context_messages(prior)
    assert len(prior) == original_len


def test_bridge_context_messages_leaves_a_correctly_shaped_transcript_untouched() -> None:
    prior = [
        {"role": "user", "content": [{"text": "hi"}]},
        {"role": "assistant", "content": [{"text": "hello"}]},
    ]
    bridged = bridge_context_messages(prior)
    assert bridged == prior
