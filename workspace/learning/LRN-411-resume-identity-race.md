---
id: LRN-411
title: Per-request state passed to worker via shared record field races
category: security
severity: high
source: redteam
date: 2026-10-17
---

## What happened
Resume code set `record.resume_identity = identity` before `deliver_resume` and cleared it to None on failure (a2a.py `_resume_or_error`, ag_ui.py resume branch). A losing concurrent resumer overwrote the winner's identity and then cleared it, so the worker kept the original submitter. Reproduced with two admin keys under asyncio.gather.

## Root cause
Identity travelled through a shared mutable field instead of atomically with the wake-up signal.

## Check
Grep `resume_identity` in agent_sdk/ and confirm no route writes it before delivery succeeds. Run a test with two concurrent resumers under different identities on both A2A and AG-UI; the handler must see the winner.

## Prevention
When planning hand-off of caller state to a running worker, put it inside the resume future's value (for example a `_ResumeEnvelope(value, identity)`), never in a shared record field a losing request can overwrite or clear.
