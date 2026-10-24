---
id: LRN-499
title: CHANGELOG bullet omits touched agent_sdk files
category: sdk
severity: high
source: redteam
date: 2026-10-24
---

## What happened
The GH-241 bullet named only `agent_sdk/agent/loop.py`. It left out `agent_sdk/models/errors.py` (new `__init_subclass__`) and `agent_sdk/__init__.py` (new `safe_joined_id_text` export). Neither basename appeared anywhere in `[Unreleased]`.

## Root cause
The bullet was written around the main fix and not checked against the full list of changed files.

## Check
For each file in `git diff --name-only -- agent_sdk/`, verify `grep -c "<basename>" CHANGELOG.md` finds it inside `[Unreleased]` (LRN-491 basename grep).

## Prevention
When planning any item, require every changed `agent_sdk/` file, including package `__init__.py` when an export is added, to be named by repo path in its CHANGELOG bullet. Run the LRN-491 grep before marking the item done.
