---
id: LRN-537
title: Behavior changes filed under Fixed
category: protocol
severity: high
source: redteam
date: 2026-10-25
---

## What happened
CHANGELOG [Unreleased] listed new rejections (AG-UI 415 for json-seq, duplicate X-Agent-Credentials key drops credentials), withheld DataParts (acceptedOutputModes, -32005) and a changed /oauth/* 429 body under `### Fixed`. [Unreleased] had no `### Changed` heading.

## Root cause
Each item was framed as a bug fix, but it can fail a run that passed before; the section was chosen by intent, not by caller impact.

## Check
Verify that every GH item in [Unreleased] that adds a rejection, drops output or changes an error body sits under `### 🔴 Breaking changes` or `### Changed`, with a ruling URL and a `**Migration:**` line (LRN-501/LRN-506).

## Prevention
When planning a changelog, classify each item by caller impact. New rejections, withheld output parts and changed error bodies go under Breaking/Changed with a Migration line, never Fixed. Add `### Changed` if missing.
