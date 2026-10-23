---
id: LRN-440
title: Every GH item needs its own CHANGELOG bullet, even additive card fields
category: ops
severity: high
source: redteam
date: 2026-10-22
---

## What happened
GH-219 added `securitySchemes.oauth2` to the public agent card and changed `security` to `[{bearer},{oauth2}]`. The [Unreleased] block had bullets for ten sibling GH items but none for GH-219.

## Root cause
Parallel groups share CHANGELOG.md, and one item's entry was assumed to cover its sibling's; additive wire fields felt too small to log.

## Check
For each GH-NNN in the wave todo, run `grep -c "GH-NNN" CHANGELOG.md` and confirm >= 1 inside [Unreleased].

## Prevention
When planning a wave, give every GH item an explicit CHANGELOG bullet task, including additive agent-card fields, and list its changed files.
