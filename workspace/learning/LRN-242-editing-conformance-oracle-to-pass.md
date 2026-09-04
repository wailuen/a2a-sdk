---
id: LRN-242
title: Conformance failure resolved by editing the portable oracle, not the code
category: protocol
severity: high
source: redteam
date: 2026-09-03
---

## What happened
Both copies of `a2ui-advisor.md` were edited this wave despite the GH-149 todo marking
them `Reads: parity check only, not modified`. The edit deletes a frozen
`TimeSeriesChart.metadata` field row and adds a normative paragraph asserting this SDK's
Python class layout ("every FROZEN type's Python model also carries `metadata`") as an
SDK-wide protocol fact — inverting the document's own stated authority ("if this document
and any implementation disagree, this document wins") and reopening, for `metadata`, the
same ungated-extension loophole GH-149 had just closed for `fund_name`.

## Root cause
Rather than land `metadata` as a versioned profile change (or drop it from the code), the
wave legitimised an SDK-specific field by editing the project-agnostic conformance
document the audit skills run against every project.

## Check
`git diff HEAD -- .claude/agents/a2ui-advisor.md harness/agents/a2ui-advisor.md` — confirm
no diff, or that any diff carries its own todo ID, a profile version bump, and a
`🔴 Breaking changes` CHANGELOG entry rather than a same-wave silent edit.

## Prevention
When planning work that touches a frozen, project-agnostic conformance document (an
advisor `.md`, a protocol profile table), require any change to it to be its own
explicitly-scoped todo with a version bump and breaking-change entry — never a same-wave
edit made to resolve that wave's own conformance failure.
