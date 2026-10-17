---
id: LRN-419
title: Parallel groups each skipped CHANGELOG entries
category: ops
severity: high
source: redteam
date: 2026-10-17
---

## What happened
`[Unreleased]` had no entry for any G2 item: GH-194, GH-196 (a breaking change: unknown tool args now rejected, `allow_extra_args`) and GH-188. The rulings required entries, and GH-196 needed a "Breaking changes" block with migration steps and the ruling URL (see LRN-153, LRN-357).

## Root cause
Groups running in parallel each assumed CHANGELOG.md was handled elsewhere, so none wrote their entries.

## Check
For every GH id in the wave, `grep -n "GH-<id>" CHANGELOG.md` matches under `[Unreleased]`. Any breaking item must sit under "Breaking changes" with migration steps and the ruling URL.

## Prevention
When planning parallel groups, assign each group explicit ownership of its own CHANGELOG entries as an AC, or add one serial final task that greps every GH id before the wave is marked done.
