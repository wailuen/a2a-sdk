---
id: LRN-212
title: Breaking CHANGELOG entry must move version/todos/register together
category: ops
severity: high
source: redteam
date: 2026-08-19
---

## What happened
CHANGELOG.md said GH-144 needs a 0.7.0 bump, not the v0.6.1 patch this wave
targets — yet pyproject.toml stayed 0.6.0, its todos stayed `- [ ]`, and
REVIEWS.md still called it "DEFER" though already fixed.

## Root cause
Version, todos, and the deferred register were updated independently, not
atomically, so the tree claimed deferred, unshipped, and breaking all at once.

## Check
When CHANGELOG.md declares a breaking/major-bump change: pyproject.toml
version matches; `grep -n "GH-" workspace/todos/active/*.md
workspace/todos/deferred/*.md` shows no `- [ ]` left for it; REVIEWS.md has
no "DEFER" row for a finding this wave already fixed.

## Prevention
When planning a wave landing a breaking CHANGELOG entry, require the version
bump, todo flip+archive, and REVIEWS.md resolution marker as one atomic
close-out, not left for later.
