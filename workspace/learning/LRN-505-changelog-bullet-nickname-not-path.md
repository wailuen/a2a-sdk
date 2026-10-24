---
id: LRN-505
title: CHANGELOG names classes or nicknames instead of repo paths
category: ops
severity: high
source: redteam
date: 2026-10-24
---

## What happened
The GH-245 bullet described changes using `ChatDriver`, `McpClient`, `run_gate` and `turns.py`, but never gave the full paths `agent_sdk/testing/chat.py`, `agent_sdk/testing/mcp.py` or `agent_sdk/testing/turns.py`. The basenames chat.py and mcp.py appeared nowhere in [Unreleased]. The test list also missed `tests/test_gh234_agui_chat_driver.py`.

## Root cause
Writers cited the class or module nickname; the LRN-491 check needs the full repo path.

## Check
For each path in `git diff --name-only -- agent_sdk harness template`, verify `grep -F '<full/path>' CHANGELOG.md` hits inside [Unreleased], and every changed test file is listed.

## Prevention
When planning a CHANGELOG bullet, require full repo paths next to each change, for both agent_sdk and harness/template workflow files, and every changed test file. A class name alone does not count.
