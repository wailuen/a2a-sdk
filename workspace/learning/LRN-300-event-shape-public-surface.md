---
id: LRN-300
title: Loop event field change is public surface, list in todo and CHANGELOG
category: sdk
severity: high
source: redteam
date: 2026-10-11
---

## What happened
GH-155 added `DoneEvent.summary` (events.py), wired `final_summary` in app.py:620, and added a `tool_choice` key to `FakeModelClient.calls` (testing/fake_model.py). None were in the todo Creates/Modifies list for the group, and CHANGELOG [Unreleased] omitted the field and the key. This failed the LRN-202 check.

## Root cause
Scope lists and CHANGELOG were written from the main feature file, not from the actual diff.

## Check
Run `git diff --name-only` and confirm every changed file appears in the todo Creates/Modifies line. grep CHANGELOG [Unreleased] for `DoneEvent.summary` and `tool_choice`.

## Prevention
When a change touches DoneEvent, other LoopEvent shapes, or FakeModelClient.calls, list events.py and testing/fake_model.py in todo scope and add CHANGELOG lines in the same change.
