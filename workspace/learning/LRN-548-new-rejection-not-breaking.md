---
id: LRN-548
title: New 4xx rejection filed under Fixed without Migration
category: protocol
severity: high
source: redteam
date: 2026-10-25
---

## What happened
GH-261 made the A2UI choice once per artifact, adding new 415 / -32005 rejections. The CHANGELOG bullet sat under Fixed with no Migration line. Requests accepted in v0.23.0 (A2UI modes without the opt-in header; resume adding the header) now fail.

## Root cause
The issue was labelled a fix, so the new rejection was not treated as a break (see LRN-371).

## Check
For each new 4xx path in the diff, `grep -n "415\|-32005" CHANGELOG.md` must hit a bullet under "Breaking changes" that contains "**Migration:**".

## Prevention
When planning, list every request the last release accepted that now gets 4xx, and require a Breaking bullet with a Migration line for each, whatever the issue label says.
