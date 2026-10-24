---
id: LRN-492
title: Failed-request rollback must restore UI, not just state
category: sdk
severity: high
source: redteam
date: 2026-10-24
---

## What happened
In console chat.js the submit handler calls `form.remove()` before `sendAgui`. When the resume POST failed, `pendingInterrupt` was restored but the form was not shown again. For multi-field interrupts, typed text hits "needs several fields; use the form" with no form on the page, so retry is impossible.

## Root cause
Rollback restored the variable only; the UI element the user needs to act was removed up front and never rebuilt.

## Check
In chat.js, verify the failed-resume branch (`if (resumed) pendingInterrupt = resumed;`) also calls `interruptForm(resumed)` when `formFields(resumed.responseSchema)` is non-null; a node or static test must cover the multi-field retry.

## Prevention
When planning optimistic UI removal before a request, require the failure path to restore every control (forms, placeholders) the user needs to retry, with a test for the multi-field case.
