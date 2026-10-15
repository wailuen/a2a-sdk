---
id: LRN-356
title: Base-class validator is a breaking change for downstream models
category: sdk
severity: high
source: redteam
date: 2026-10-15
---

## What happened
GH-173 added a finite-float validator to `_Wire`/`ContentModel`. The CHANGELOG filed it under `### Fixed` and scoped it to built-in models. It also hits every agent's domain subclass, so a `float` field with nan/inf now fails tool output.

## Root cause
A validator on a shared base class was described by where it was written, not by who inherits it.

## Check
Verify the CHANGELOG entry for any `_Wire`/`ContentModel` validator or config change (e.g. `hide_input_in_errors`) sits under `Breaking changes`, names domain subclasses, and has a **Migration:** line: `grep -n "Migration" CHANGELOG.md`.

## Prevention
When planning a validator or config change on a shared base class, require a Breaking bullet that covers all subclasses, plus a Migration line (for example `float | None`).
