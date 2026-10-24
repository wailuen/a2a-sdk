---
id: LRN-507
title: Provisional testing surface rejections need Breaking heading
category: ops
severity: high
source: redteam
date: 2026-10-24
---

## What happened
GH-245 added new client-side rejections in `agent_sdk.testing` (a2a_turn rejects a card with no `preferredTransport`, run_gate fails on structuredContent mismatch, acceptance-api.js throws on bad `transports`/`onlyIds`). They were filed under Changed with no Migration line and no Breaking heading in `[Unreleased]`.

## Root cause
The surface is labelled provisional, so the author assumed LRN-501 did not apply.

## Check
Grep CHANGELOG.md `[Unreleased]` for `### 🔴 Breaking changes` and confirm each GH-245 rejection bullet sits under it with a `**Migration:**` line. Confirm only one Unreleased heading exists.

## Prevention
When planning any change that makes `agent_sdk.testing` reject input it used to accept, add a task to list it under Breaking changes with a Migration line, editing the single Unreleased section in place.
