---
id: LRN-462
title: Redaction fix must be mirrored across both wave runners
category: security
severity: high
source: redteam
date: 2026-10-23
---

## What happened
The same weak redaction (LONG `{40,}`, no `/`, no JWT/Google/Basic/glpat/pk_live/`password=` patterns) existed in .claude/workflows/sdk-wave.js, so those secrets could be posted to a public issue from either runner.

## Root cause
The filer script is duplicated in wave-cycle.js and sdk-wave.js; a gap fixed in one is silently left in the other.

## Check
Verify the redaction pattern block is identical in both files: `grep -n "LONG = re.compile" harness/workflows/wave-cycle.js .claude/workflows/sdk-wave.js` shows the same regex, and the parity test passes.

## Prevention
When planning a change to FILE_SDK_ISSUES_PY or any shared embedded script, list both runners (and the template mirror) as units and add a parity test comparing the embedded text.
