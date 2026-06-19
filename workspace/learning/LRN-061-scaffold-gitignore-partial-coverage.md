---
id: LRN-061
title: Credential gitignore globs missing from secondary scaffold path
category: security
severity: critical
source: redteam
date: 2026-06-15
---

## What happened
The `new-agent` scaffold skill received ADR credential globs (`workspace/adr/ADR-000-*-credentials.md` and `workspace/adr/ADR-001-*-credentials.md`) and a `git check-ignore` verification probe as part of the LRN-050 / GH-66 fix. The `setup` skill was not updated in the same wave, leaving its `.gitignore` block without those globs and without any verification probe. A project initialized via `setup` would silently commit credential inventory files.

## Root cause
The fix was applied to only one of the two scaffold paths. Partial coverage of a security control is equivalent to no coverage on the unfixed path.

## Check
`grep -n "ADR-000-\*-credentials\|ADR-001-\*-credentials" harness/skills/setup/SKILL.md` must return at least two matches; and `grep -n "git check-ignore" harness/skills/setup/SKILL.md` must return at least one match.

## Prevention
When a credential-glob or `.gitignore` fix is applied to any scaffold skill, apply the identical glob set AND the `git check-ignore` verification probe to every other scaffold path (setup, new-agent, migrate, etc.) in the same commit — partial coverage reintroduces the LRN-050 critical gap on every unfixed path.
