---
id: LRN-511
title: Ruling URL must cover each Breaking part exactly
category: protocol
severity: high
source: redteam
date: 2026-10-24
---

## What happened
The run_gate bullet (fails a tool whose `structuredContent` is absent or does not match its `outputSchema`) sat under Breaking with no ruling URL. MCP 2025-06-18 requires conforming structuredContent, but no maintainer ruling covered shipping the stricter gate.

## Root cause
One ruling (or none) was assumed to cover every part of a multi-part issue. Part 4 of GH-245 had no ruling of its own.

## Check
For each Breaking bullet in `[Unreleased]`, grep for an `issues/NNN#issuecomment-` URL and confirm the linked comment names that specific item. Confirm tools returning None are handled consistently by the gate and the server.

## Prevention
When planning a multi-part issue, require a ruling URL per Breaking part. Otherwise reclassify the part under Changed with a provisional notice.
