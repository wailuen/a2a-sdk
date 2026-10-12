---
id: LRN-308
title: Debug-round fix silently narrowed a maintainer-ruled behavior
category: sdk
severity: high
source: redteam
date: 2026-10-11
---

## What happened
The GH-155 ruling says that on max_turns or token-budget exit, make one final tools-disabled call. A w045 round-4 debug fix made `_summary_max_tokens` charge the transcript re-send against the 1024 allowance. With defaults, a budget exit almost always skips the call and sends the fixed notice, which the ruling allowed only on call failure. It was deferred as medium with no approval.

## Root cause
A wave-internal debug reinterpretation was treated as settled; a proposal is not maintainer sign-off.

## Check
Verify a default-settings test where a budget exit produces a real model summary (not the fixed notice). grep CHANGELOG and docs/deployment.md for "usually sends the fixed notice" and confirm no match.

## Prevention
When a fix would change behavior a maintainer ruling mandates, escalate and get a GH comment URL before landing. Do not defer such a deviation as medium.
