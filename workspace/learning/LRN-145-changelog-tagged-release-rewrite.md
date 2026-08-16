---
id: LRN-145
title: Changelog entries must land under Unreleased, not inside an already-tagged release section
category: ops
severity: high
source: redteam
date: 2026-08-15
---

## What happened
The GH-134 entry was inserted into the `## [0.5.44] — 2026-07-24` section of
`CHANGELOG.md`, but `v0.5.44` is an existing tag (commit 65c6c5f, an ancestor
of HEAD) that never contained this change — rewriting a shipped release's
history. It was also filed under `### 🟡 Protocol surface changes` despite
flipping `openWorldHint` False→True for every SourceAdapter-backed tier-1
tool, a wire-visible MCP consent-UI classification change that belongs under
`### ⚠️ Behavior changes`. GH-129/130/131/132/133/135/139 had no entries at
all.

## Root cause
Changelog authoring appended to the nearest existing version heading instead
of checking whether that heading was already tagged, and classified by
section label ("Protocol surface") rather than by wire impact (consent-UI
classification = Behavior change).

## Check
`git tag --contains <fix-commit>` for any commit touched by a changelog
entry — if the entry's target section corresponds to a tag that already
contains that commit as an ancestor, or the tag predates the fix commit, the
entry landed in the wrong section. Also grep `CHANGELOG.md` for `##
\[Unreleased\]` and confirm it exists and precedes the newest tagged section
whenever any commit lands after the last tag.

## Prevention
When planning a changelog update, first run `git describe --tags` /
`git tag --contains HEAD` to find the last tag; any change made after that
tag goes under a `## [Unreleased]` heading at the top of the file, never
into an existing tagged section. Classify by wire impact, not label: a
change to any MCP annotation (`openWorldHint`, `readOnlyHint`, etc.) or a
caller-visible exception type is a Behavior change, not a Protocol surface
note.
