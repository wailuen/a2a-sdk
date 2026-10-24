---
id: LRN-517
title: Import-time or helper-output changes need a Breaking changes entry
category: sdk
severity: high
source: redteam
date: 2026-10-24
---

## What happened
GH-250 made a `SafeValueError` subclass with an empty cleaned `message` raise TypeError at import. It also changed the output of `safe_line_text`, `safe_cell_text`, `safe_id_text` and `safe_joined_id_text` for Cf characters (ZWJ, ZWNJ, BOM, ZWSP). The CHANGELOG filed it only under `### Fixed`; [Unreleased] had no Breaking changes entry.

## Root cause
The ruling called the change hardening, so the author classified it as a fix and skipped the breaking-change rule (LRN-472).

## Check
Verify that when `git diff -- agent_sdk` changes an exported stable-core helper's output or adds an import-time raise, the CHANGELOG [Unreleased] section has a `### 🔴 Breaking changes` heading with a `**Migration:**` line naming that GH issue.

## Prevention
When planning a change that makes existing definitions fail at import or alters an exported stable-core helper's return value, add a CHANGELOG Breaking changes bullet with Migration and the ruling URL to the todo, even if the ruling calls it hardening.
