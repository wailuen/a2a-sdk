---
id: LRN-141
title: Deferred background awaiter leaks raw Reusable wrapper onto the wire
category: sdk
severity: high
source: redteam
date: 2026-09-02
---

## What happened
`_run_deferred_background` (runner.py:485) resolves a deferred tool's `Reusable` result but never unwraps it before folding into `record.messages`. The raw dataclass repr reaches the A2A/AG-UI wire and no `__resolved__` marker is added, so GH-148 reuse tracking is dead for long-running resolver tools.

## Root cause
`Reusable` unwrapping was added only at `invoke_any` (registry.py:634) and `loop.py`'s synchronous branch — the background deferred awaiter bypasses both and folds `raw_result` directly.

## Check
`grep -n "isinstance.*Reusable" agent_sdk/agent/runner.py` must show an unwrap in `_run_deferred_background`; add a regression test asserting `"Reusable(" not in repr(record.messages)` for a deferred resolver tool, alongside `tests/test_rt004_deferred_transcript_parity.py`.

## Prevention
When planning a new tool-result wrapper class (e.g. `Reusable`, `DeferredResult`), enumerate every dispatch surface that can be the *last* handler of a resolved value (sync loop, MCP `tools/call`, deferred background awaiter) and require an explicit unwrap test per surface — never assume one shared helper covers all paths (see LRN-120).
