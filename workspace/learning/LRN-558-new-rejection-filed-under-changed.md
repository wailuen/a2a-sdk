---
id: LRN-558
title: New rejection filed under Changed instead of Breaking
category: sdk
severity: high
source: redteam
date: 2026-10-25
---

## What happened
The GH-264 entry said `McpClient.initialize` now raises `McpError` when `protocolVersion` is missing, and called it "breaking". It sat under `### Changed` with no **Migration:** line. The GH-256 precedent put the same kind of change under Breaking. This failed LRN-321 and LRN-153.

## Root cause
A silent fallback turned into an exception was treated as a behaviour tweak, and the word "breaking" in prose was taken as enough.

## Check
Verify that any CHANGELOG sentence containing "breaking" or "raises" for a new rejection sits under `### 🔴 Breaking changes` and has a `**Migration:**` line plus a ruling URL.

## Prevention
When planning a change that turns a silent fallback into an exception (including in testing clients), place it in its own Breaking bullet with Migration and ruling URL. Keep the rest of the entry under Changed.
