---
id: LRN-506
title: New API and breaking behaviour filed only under Fixed
category: ops
severity: high
source: redteam
date: 2026-10-24
---

## What happened
The GH-245 bullet put new public API (`skills_tool`, `--skills-tool`, `A2AError.AUTHENTICATED_EXTENDED_CARD_NOT_CONFIGURED`) and behaviour changes (cards without `preferredTransport` now rejected, stricter gate, new McpClient header) all under `### Fixed`. [Unreleased] had no `### Added` or `### Changed`.

## Root cause
Every wave item was treated as a bug fix, so the Added/Changed split required by LRN-498 and LRN-494 was skipped.

## Check
Verify [Unreleased] contains one `### Added` and one `### Changed` when the diff adds an exported keyword, CLI flag or constant, or changes behaviour that can fail a previously passing run. Inspect with `sed -n '/^## \[Unreleased\]/,/^## \[[0-9]/p' CHANGELOG.md | grep '^###'`.

## Prevention
When planning, classify each change: new keyword, flag or constant goes under Added; any change that can fail a run that passed before goes under Changed; Fixed only for plain bug fixes.
