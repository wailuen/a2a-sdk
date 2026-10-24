---
id: LRN-504
title: Shipped agent_sdk module imports a dev-only package
category: sdk
severity: high
source: redteam
date: 2026-10-24
---

## What happened
`agent_sdk/testing/mcp.py` imported `jsonschema` at top level, but jsonschema is only in the `[dev]` extra of pyproject.toml. In downstream agents, `python -m agent_sdk.testing.mcp` and `from agent_sdk.testing import McpClient` fail with ModuleNotFoundError.

## Root cause
Tests ran with dev extras installed, hiding that the shipped module needs a package outside `[project].dependencies`.

## Check
Run a test that parses every top-level third-party import under `agent_sdk/` (testing/ included) and asserts each is in `[project].dependencies`. Manually: `grep -n '^import jsonschema' agent_sdk/` must match only if pyproject lists it.

## Prevention
When planning a change that adds an import to any shipped agent_sdk module, require either adding the package to `[project].dependencies` (lower bound only, DESIGN.md §10.3) with a CHANGELOG line, or a lazy import with a fixed failure message.
