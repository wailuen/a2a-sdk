"""echo-analyst — the built-in example agent (DESIGN.md §3, §12).

The CI gate boots this agent on a real port and runs the live probe suite
against it. It exercises every SDK surface with no external dependencies:
a Tier 1 tool emitting a Profile type, a Tier 2 composite tool, a skill,
and an interrupting (confirm-style) tool.

Run locally::

    DEV_MODE=true .venv/bin/uvicorn agent_sdk.example.main:app --port 8000
"""
