---
id: LRN-176
title: Todo checked [x] with a "Landed:" note despite an unenacted peer-repo diff
category: testing
severity: high
source: redteam
date: 2026-08-15
---

## What happened
GH-131 and GH-132 both declared `template/.claude/workflows/wave-cycle.js`
(the peer-repo runtime mirror) as a deliverable and both todos were marked
`[x]` with "Landed:" notes. `template/` is absent from this checkout, so
neither fix ever reached the peer clone — the file still has the pre-fix
code. The only guards for it, `test_wave_cycle_is_harness_template_shared`
and `test_acceptance_api_is_harness_template_shared`, are
`xfail(strict=True)`, so pytest reports green.

## Root cause
`[x]` + a "Landed:" note is a self-attested completion claim, never checked
against the actual diff at the declared path. Nothing compares the note's
claim to `git diff`/file contents before the todo is trusted as done.

## Check
For any todo with a `template/`-path Creates:/Modifies: entry marked `[x]`,
run `test -d template && diff <src> template/<path>`; a nonexistent
`template/` or nonempty diff means the "Landed:" note is false and the todo
must be reopened, regardless of suite exit code.

## Prevention
When planning a wave with a `template/` peer-repo deliverable, require the
implementer to attach the actual `diff`/commit SHA proving the copy landed
before checking `[x]` — a prose "Landed:" note alone must never satisfy the
archive gate.
