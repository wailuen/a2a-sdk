---
id: LRN-433
title: CHANGELOG must name every changed file and new public method
category: sdk
severity: high
source: redteam
date: 2026-10-19
---

## What happened
The [Unreleased] entry for GH-202 named only 2 of 7 changed agent_sdk files. The new public CredentialStore.list_items (class exported in agent_sdk.credentials.__all__) had no ### Added line, and the new lock and race fixes and test file were not mentioned.

## Root cause
The CHANGELOG was written from the headline fix, not from the diff file list, so LRN-379 and LRN-202 checks failed.

## Check
For each `git diff --name-only -- agent_sdk` basename, grep the text between [Unreleased] and the previous release heading in CHANGELOG.md and confirm a match. Confirm every new method on an `__all__` class has its own ### Added bullet.

## Prevention
When planning a release-bound change, add a todo to list each changed agent_sdk file by basename, add an ### Added line per new public method, and list new test files.
