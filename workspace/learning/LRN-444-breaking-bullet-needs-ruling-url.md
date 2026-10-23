---
id: LRN-444
title: Breaking CHANGELOG bullet admitting no ruling URL blocks the wave
category: ops
severity: high
source: redteam
date: 2026-10-22
---

## What happened
The GH-221 Breaking-changes bullet said no owner ruling comment exists on issue 221. The only maintainer comment rules on part 4 onward, not parts 1-3 (-32601 to -32602, empty 202, GET /mcp 404/400). This fails the LRN-384 check.

## Root cause
The breaking change was implemented and disclosed without first obtaining a maintainer ruling covering all its parts.

## Check
Confirm every Breaking bullet in [Unreleased] contains an `issues/NNN#issuecomment-` URL, and `grep -n "no owner ruling" CHANGELOG.md` returns nothing.

## Prevention
When planning, treat a breaking change as blocked until a ruling comment covering every part is recorded on the issue; never ship a bullet that merely discloses its absence.
