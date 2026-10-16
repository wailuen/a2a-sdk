---
id: LRN-402
title: Fixing one secret-printing step, sibling left leaking
category: security
severity: high
source: redteam
date: 2026-10-16
---

## What happened
GH-183 fixed the service key mint in agent-verify. Phase 1 step 3, the bootstrap mint of the admin key, still had no command or output handling, so its response (with the admin key `plaintext`) printed to the transcript. Step 4 also referred to a credentials file that agent-verify does not have.

## Root cause
The fix covered one mint step; the upstream step that authorizes it was not audited for the same leak.

## Check
Test: extend test_mint_block_static_shape to cover the bootstrap mint block. Confirm neither the plaintext nor the token reaches stdout. `grep -n "plaintext" harness/skills/agent-verify/SKILL.md`.

## Prevention
When planning a fix to a secret-leaking step, enumerate every mint/issue step in the same skill, including upstream credentials, and fix them together. Check that each referenced secret source exists.
