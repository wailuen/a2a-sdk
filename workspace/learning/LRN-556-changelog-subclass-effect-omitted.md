---
id: LRN-556
title: Breaking CHANGELOG entry omits effect on downstream subclasses
category: sdk
severity: high
source: redteam
date: 2026-10-25
---

## What happened
The GH-262 item 4 Breaking bullet narrowed `TimeSeriesChart.x_key`/`y_key` to `Literal["date"]`/`Literal["value"]` with a new validator. It did not say that domain subclasses inherit the Literal type and the check. This failed the LRN-356 check and the deferred GH-258 note.

## Root cause
The entry described the base-class change only. Nobody asked who inherits the shared ContentModel.

## Check
Verify that every Breaking bullet in `[Unreleased]` of CHANGELOG.md that changes a field type or validator on a shared ContentModel contains the word "subclass" (grep -n "ubclass" CHANGELOG.md). Quote the new rejection messages verbatim.

## Prevention
When planning a validator or field-type change on a shared ContentModel, add a CHANGELOG acceptance item: the Breaking bullet names the effect on downstream subclasses and gives the migration for subclasses with their own keys (LRN-356).
