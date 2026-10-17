---
id: LRN-424
title: Todo-required CHANGELOG entry lost in shared file
category: ops
severity: high
source: redteam
date: 2026-10-17
---

## What happened
The GH-190 todo required a CHANGELOG Fixed entry, but `[Unreleased]` had none. Four new pushNotificationConfigs routes would have shipped unannounced and the todo's last acceptance condition was unmet.

## Root cause
Several groups edit CHANGELOG.md in one wave, and one group's entry was lost or never written; nothing verified it before marking the todo done.

## Check
`grep GH-190 CHANGELOG.md` must match. For every GH-NNN in the wave's todos that lists a CHANGELOG entry, `grep GH-NNN CHANGELOG.md` must match.

## Prevention
When planning waves where groups share CHANGELOG.md, add a final verification step that greps each issue id in CHANGELOG.md before any todo is marked done.
