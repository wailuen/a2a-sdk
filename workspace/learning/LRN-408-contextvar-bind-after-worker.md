---
id: LRN-408
title: ContextVar bound around hand-off to a running worker is a no-op
category: sdk
severity: high
source: redteam
date: 2026-10-17
---

## What happened
GH-185 bound the caller identity around `_resume_or_error` and `_open_stream` in routes/a2a.py. Resume only calls `store.deliver_resume()`, so the existing worker kept the original submitter's identity. The test spied on the ContextVar inside the route, which no tool reads.

## Root cause
A ContextVar reaches only tasks created inside the bound window; the worker was created earlier on the original submit.

## Check
Run an end-to-end test: a tool raises an interrupt, a different allowed caller (admin key) resumes, and the post-resume tool reports that caller. Grep that `bind_identity` is called inside the worker (runner.py) after resume, not only in routes.

## Prevention
When planning per-request context for work done by a long-lived worker, pass the value through the hand-off (resume payload) and rebind in the worker's own context. Require tests to assert what the tool sees, never the variable inside the route.
