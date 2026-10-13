---
id: LRN-321
title: Wire break filed under Fixed, not Breaking changes
category: protocol
severity: high
source: redteam
date: 2026-10-13
---

## What happened
GH-158 removed the always-present `parentMessageId` key from TOOL_CALL_START. GH-159 added -32005/HTTP 415 and -32602 rejections for input that used to return 200. Both sat under `### Fixed` with an inline "Behavior change:" and no Migration callout or spec citation, forfeiting the DESIGN.md §4.0 conformance exemption.

## Root cause
Conformance-driven wire changes were treated as ordinary bug fixes (LRN-153/LRN-201 not applied).

## Check
In CHANGELOG.md `[Unreleased]`, confirm each key removal or new rejection code is under `### 🔴 Breaking changes` with a `**Migration:**` line and a spec clause citation.

## Prevention
When planning a wave that changes wire shape or adds rejection codes, include a changelog task: Breaking section, Migration callout, spec citation.
