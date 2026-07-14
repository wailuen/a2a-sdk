---
id: LRN-119
title: Mid-wave module extraction omitted from Creates: ships unimportable pkg
category: ops
severity: high
source: redteam
date: 2026-07-14
---

## What happened
GH-110 extracted `agent_sdk/common/origin.py` (`guard_origin`), imported by all three protocol route modules. The todo's `Creates:` named only route/test files — the module was undeclared and git-untracked (`??`).

## Root cause
Shared logic was factored into a new file mid-wave without updating the todo's scope, so an archive commit staging only declared paths silently omits it — ImportError at boot on every importing surface.

## Check
Diff declared paths vs `git status --short`; any `??` `.py` file imported by a declared file must itself appear in that todo's Creates:. Confirm `git ls-files <path>` non-empty pre-archive.

## Prevention
When implementation adds a module not named in a todo, add it to Creates: and stage it explicitly pre-archive; confirm via `git ls-files` post-commit. Same class as LRN-052/056.
