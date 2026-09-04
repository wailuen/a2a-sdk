---
id: LRN-233
title: New hook name collides with a pre-existing private method, breaks import
category: sdk
severity: high
source: redteam
date: 2026-09-03
---

## What happened
`ContentModel.__init_subclass__` raises `TypeError` at class-definition
time when a subclass defines both `_body_text()` and `to_plain_text()`.
Before this release `_body_text` had no meaning, so a domain card using
it as an ordinary private helper alongside `to_plain_text()` now fails to
import — while the CHANGELOG says "Migration: none required" twice.

## Root cause
The release reserved a new name (`_body_text`) on a public base class
without checking whether existing subclasses already used that name for
something unrelated; "none required" was asserted without that check.

## Check
`grep -rn "_body_text" agent_sdk/ tests/ | grep -v content_types.py` to
enumerate any pre-existing subclass defining it, then confirm each still
imports after the change. Any newly-reserved name on a public extension
base class needs the same grep before a "no migration" claim ships.

## Prevention
When planning a change that adds a hook/reserved name to a public base
class, require a repo-wide grep for that exact name across all
subclasses before writing "Migration: none required" — treat any hit as
a breaking change needing a callout, not a no-op.
