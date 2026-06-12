---
name: codify
category: core
description: "Turn a bug, fix, gotcha, or validated pattern from an agent-sdk agent into a permanent learning in workspace/learning/. Auto-invoked by /agent-verify on critical findings."
---

# /codify — Capture a learning

Turn an execution outcome into a permanent `LRN-NNN` record in
`workspace/learning/`. Covers bugs, security findings, validated patterns,
and SDK sharp edges.

## Usage

```
/codify <description>
```

Examples:
- `/codify SourceAdapter.health_check must be idempotent — called at boot and
  on every liveness probe`
- `/codify url_segment() rejects path traversal but not Unicode lookalikes —
  test with real inputs, not synthetic strings`
- `/codify FakeModelClient tool_call must match the registered tool name exactly
  — silent mismatch silently skips the tool`
- `/codify rate gate is adapter-wide, not per-caller — one slow caller can
  starve others`

## Steps

1. Parse `$ARGUMENTS` for the learning description.
2. Ensure `workspace/learning/README.md` exists. If missing, create it with the
   standard header (see `workspace/learning/README.md` as template).
3. Read `workspace/learning/README.md` to check for duplicates by scanning the
   description column. If a similar learning exists, offer to update it instead
   of creating a new entry.
4. Determine category from context:
   - `security` — credential handling, injection, auth bypass
   - `protocol` — A2A / AG-UI / A2UI / MCP wire conformance
   - `sdk` — SDK sharp edges, install/boot, contrib limitations
   - `testing` — FakeModelClient, ChatDriver, test isolation
   - `ops` — deployment, rotation, credential seeding
5. Write `workspace/learning/LRN-NNN-[slug].md` with the schema below. Keep it
   under 1 KB; if the description is long, trim to the core invariant.
6. Append a row to `workspace/learning/README.md`.
7. Report: LRN ID, category, and the check clause added.

## Learning record schema

```markdown
---
id: LRN-NNN
title: <short title — one sentence>
category: security | protocol | sdk | testing | ops
severity: critical | high | medium | low
source: redteam | implement | smoke-test | manual
date: YYYY-MM-DD
---

## What happened
<2-3 sentences>

## Root cause
<1-2 sentences>

## Check
<specific grep or test to verify — e.g. "grep for X in src/" or "run test Y">

## Prevention
<actionable planner constraint — "When planning..., ensure...">
```

## Convention for callers

Any skill that surfaces a failure should invoke `/codify` with the root cause
and resolution rather than reporting it inline only. Specifically:
- **`/agent-verify`** — should codify any critical/high finding before closing
  the report (the verify skill's steps are the trigger point)
- **`/scenario --live`** — should codify any live-test failure before continuing

This is a convention, not automatic execution — the calling skill must
explicitly invoke `/codify <finding>` as a step.
