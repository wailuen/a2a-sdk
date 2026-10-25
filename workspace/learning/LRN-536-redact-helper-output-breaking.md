---
id: LRN-536
title: Hardening a stable-core redact helper's output is Breaking
category: sdk
severity: high
source: redteam
date: 2026-10-25
---

## What happened
GH-251 changed the output of `safe_block_text` in `agent_sdk/common/redact.py`, exported from `agent_sdk/__init__.py`. It was filed only under `### Fixed`. The new output also strips U+200C and U+200D: `safe_block_text('می‌خواهم 👨‍👩‍👧')` gives `'میخواهم 👨👩👧'`, which breaks Persian spelling and emoji sequences.

## Root cause
The ruling called the change hardening, so no one classified the output change as Breaking (LRN-517).

## Check
Confirm `### 🔴 Breaking changes` in [Unreleased] has a GH-251 bullet with the ruling URL and a `**Migration:**` line about ZWJ/ZWNJ. Or run `safe_block_text('می‌خواهم')` and confirm U+200C is kept.

## Prevention
When planning a change to any exported stable-core redact helper, treat an output change as Breaking. Probe non-Latin and emoji inputs, and ask for a ruling on format characters that carry meaning.
