---
id: LRN-153
title: Breaking changes filed under the wrong CHANGELOG heading forfeit the §4.0 exemption
category: ops
severity: high
source: redteam
date: 2026-08-15
---

## What happened
GH-134 (MCP `tools/list` annotations/openWorldHint wire-shape change) and
GH-135 (ValidationError→ToolInputValidationError dispatch break) were both
filed under `### ⚠️ Behavior changes` in CHANGELOG.md instead of
`### 🔴 Breaking changes`. Neither carried the Migration callout DESIGN.md
§4.0 requires, so GH-134's patch-bump exemption is invalid and GH-135 (a
voluntary break, exemption-ineligible by §4.0) shipped unflagged as major.

## Root cause
Changelog authoring classified by perceived magnitude ("behavior" sounds
softer than "breaking") rather than by checking §4.0's exemption
prerequisites — a dedicated 🔴 heading, dual-direction wire impact, and an
explicit Migration callout — before deciding a change could avoid a major
bump.

## Check
For each CHANGELOG entry referencing an exception-type change or an MCP
annotation/field-shape flip (`openWorldHint`, `readOnlyHint`, `annotations`,
etc.), grep for `Migration` in that entry's block and confirm it sits under
`### 🔴 Breaking changes`, not `### ⚠️ Behavior changes`.

## Prevention
When planning a changelog update for any stable-core wire or exception-type
change, check DESIGN.md §4.0's exemption prerequisites first: require a
`### 🔴 Breaking changes` heading naming the exact type/field, both emit and
parse impact, and a Migration callout — before filing under `⚠️ Behavior
changes` or claiming a patch bump. Voluntary (non-spec-driven) breaks are
exemption-ineligible regardless of heading.
