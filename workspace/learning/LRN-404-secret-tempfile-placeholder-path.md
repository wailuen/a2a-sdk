---
id: LRN-404
title: Secret temp file path built from placeholder or guessable name
category: security
severity: high
source: redteam
date: 2026-10-16
---

## What happened
The acceptance skill Phase 0 minted a service key into `/tmp/acc-key-<run-id>.txt`. The run-id is only defined in a later phase and is guessable (run-001), so concurrent runs clobbered each other's key and teardown `rm -f` deleted a live key. A pre-created 666 file on shared /tmp would also capture the plaintext key.

## Root cause
Path built from a placeholder defined later, instead of a fresh unpredictable path created in the same command; no ownership/mode check before writing.

## Check
Verify the mint block in `harness/skills/acceptance/SKILL.md` uses `mktemp` for the key path: `grep -n "acc-key" harness/skills/acceptance/SKILL.md` must show no `<run-id>`, and the writer opens with `O_NOFOLLOW` plus an `os.fstat` uid/0o600 check.

## Prevention
When planning skills that write secrets to disk, require a `mktemp`-created path inside the same command, printed back to the agent, with fail-closed owner/mode checks. Never derive it from a later-defined placeholder.
