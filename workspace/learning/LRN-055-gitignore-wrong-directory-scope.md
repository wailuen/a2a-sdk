---
id: LRN-055
title: gitignore placed in wrong directory fails to protect credential files
category: security
severity: high
source: redteam
date: 2026-06-15
---

## What happened

GH-66's credential-protection fix added `ADR-001-*-credentials.md` globs to `harness/.gitignore`, which only matches paths relative to `harness/`. The `/provision` skill writes credential inventory files to the agent repo's top-level `workspace/adr/`, which is never covered by `harness/.gitignore`. The scaffold seed file `template/.gitignore` — the file `/new-agent` Phase 2 actually copies into each new agent repo — was also missing the `ADR-001-*-credentials.md` glob, so every agent scaffolded after the wave remained unprotected.

## Root cause

A `.gitignore` file only matches paths relative to its own directory; placing credential-protection globs in `harness/.gitignore` instead of the file seeded to the agent repo root (`template/.gitignore` or the runtime-appended root `.gitignore`) means the globs never apply where credentials actually land.

## Check

From a freshly-scaffolded agent repo root, run:

```
git check-ignore -v workspace/adr/ADR-001-dev-credentials.md
```

If the command prints nothing (no match), the protection is missing. Also verify:

```
grep -n 'ADR-001' .gitignore
```

Must return at least one matching glob line.

RT-005/RT-014: checks the root `.gitignore` that actually protects
`workspace/adr/` in this checkout (the "runtime-appended root .gitignore"
outcome this learning asks for), not `template/.gitignore` directly — the peer
repo (LRN-071) is not always checked out locally. Note this is deliberately
NOT `harness/.gitignore`: that was the wrong-scope location this learning
exists to document, so repointing there would silently reintroduce the bug
this Check is meant to catch.

## Prevention

When planning any credential-file protection via `.gitignore`, place globs in the `.gitignore` that is seeded to the agent repo root (`template/.gitignore` or the step in `/new-agent` that writes the root `.gitignore`). Never rely on `harness/.gitignore` to protect files written outside `harness/`. Validate with `git check-ignore -v <path>` from the target repo root before closing the issue.
