---
id: LRN-443
title: CHANGELOG Changed list must come from git diff, not headline fix
category: ops
severity: high
source: redteam
date: 2026-10-22
---

## What happened
The GH-213 [Unreleased] entry never named agent_sdk/a2ui/translator.py (A2uiCapabilities.from_metadata), DESIGN.md section 5.4, docs/protocols.md or the w051 deferred file. This is a recurrence of LRN-433.

## Root cause
The bullet was written from the headline fix instead of from the actual changed-file list.

## Check
Between [Unreleased] and the previous release heading in CHANGELOG.md, grep for each production file in `git diff --name-only -- agent_sdk docs DESIGN.md` and confirm a match.

## Prevention
When planning, require each per-GH CHANGELOG bullet to end with a `Changed:` list built from `git diff --name-only` for that item.
