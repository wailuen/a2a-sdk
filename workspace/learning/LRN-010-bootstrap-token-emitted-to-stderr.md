---
id: LRN-010
title: SDK bootstrap token is emitted to stderr, not stdout; boot capture must use 2>&1
category: ops
severity: high
source: redteam
date: 2026-06-14
---

## What happened

Phase 5 of the setup skill (harness/skills/setup/SKILL.md) documented the first-run boot command without stderr redirection (`> "$tmplog"` only, no `2>&1`), and step 5 described the bootstrap token as being "printed to stdout". In reality, `agent_sdk/auth/api_keys.py` emits the bootstrap token via `print(..., file=sys.stderr)`. A tempfile capturing only stdout silently receives nothing, leaving the setup flow blocked waiting for a token that will never appear in the log.

## Root Cause

The SKILL.md author assumed the token was written to stdout (the conventional channel for machine-readable output). The SDK instead writes it to stderr to keep it out of structured stdout streams. The mismatch went undetected because the boot command still launched successfully — only the token extraction step failed at runtime.

## Prevention

Any process that must capture output from the SDK bootstrap sequence must redirect both stdout and stderr to the capture file: `... > "$tmplog" 2>&1`. When documenting boot commands in skill files or runbooks, explicitly state which file descriptor carries the bootstrap token. If the emission channel changes in a future SDK release, update both `api_keys.py` and the setup skill in the same commit.
