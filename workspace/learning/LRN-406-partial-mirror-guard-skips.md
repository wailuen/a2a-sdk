---
id: LRN-406
title: Mirror guard skips or checks only a fragment
category: testing
severity: high
source: redteam
date: 2026-10-16
---

## What happened
`test_skill_copies_use_same_block` skipped when the template copy was missing and compared only the mint block. Existing parity tests covered harness vs `.claude/` only, and the pushed-mirror test covered only `.claude/workflows/`. A broken template scriptPath and unpushed edits passed all 181 related tests.

## Root cause
Guard tests used silent skip and fragment comparison, so whole-file drift and unpushed state in the peer repo went unchecked.

## Check
Verify `grep -n "pytest.skip" tests/test_gh183_184_service_key_mint_step.py` shows no skip for the template copy, and a test diffs harness vs template for both skills allowing only the scriptPath line and checks `.claude/skills/*` against `@{upstream}`.

## Prevention
When planning mirror guards, require a whole-file diff with an explicit allow-list, a hard failure (or the LRN-162/174 checkout gate) when the peer is absent, and a pushed-commit check covering every mirrored path.
