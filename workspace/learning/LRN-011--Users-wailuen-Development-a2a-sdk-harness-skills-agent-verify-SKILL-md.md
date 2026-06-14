---
id: LRN-011
severity: high
title: Bootstrap token goes to stderr; agent-verify boot command must use 2>&1
category: ops
source: redteam
date: 2026-06-14
---

## Observation

`agent-verify/SKILL.md` Phase 1 step 1 (lines 48-49) instructs the agent to "Run it in the background; capture stdout (the first-run bootstrap token prints there)". The boot command at line 40 does not include `2>&1`. In reality, `BootstrapManager.arm_if_needed()` in `agent_sdk/auth/api_keys.py` (line 154) prints the bootstrap token to `sys.stderr`, not `sys.stdout`. An agent following these instructions captures only stdout, never sees the token, and the mint-key step fails.

## Root Cause

The skill was written assuming the bootstrap token appears on stdout, but the SDK deliberately routes it to stderr to keep it out of structured log pipelines. The already-correct `provision/SKILL.md` uses `> "$tmplog" 2>&1 &`, but `agent-verify/SKILL.md` was not kept in sync with that pattern when the skill was authored.

## Prevention

All skill boot commands that need to capture the bootstrap token must use `> "$tmplog" 2>&1 &` and document "capture stderr (redirected via 2>&1)". When updating any skill that starts the agent subprocess, cross-check against `provision/SKILL.md`'s boot command as the canonical reference.
