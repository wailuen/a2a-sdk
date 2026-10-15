---
id: LRN-395
title: Mirrored SKILL.md copies diverge on security rules
category: ops
severity: high
source: redteam
date: 2026-10-15
---

## What happened
The harness acceptance SKILL.md got the new service-key secret-handling rule, but the template copy still said the admin key is read from ADR-000. Agent repos run the template copy, so they got the stale rule. Template edits were also left uncommitted in the template peer repo.

## Root cause
Only the edited hunks were mirrored; whole-file divergence between copies was not checked.

## Check
Run `diff harness/skills/acceptance/SKILL.md template/.claude/skills/acceptance/SKILL.md` and confirm the only difference is the scriptPath/.claude/workflows line. Confirm the template repo has no uncommitted changes (LRN-071, LRN-208).

## Prevention
When a wave edits a mirrored SKILL.md, diff the whole file against every sibling copy, record allowed diffs, and commit the template repo as part of the release.
