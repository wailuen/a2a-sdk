---
id: LRN-083
title: Reverse HTTP→A2A error map must not attribute generic 404s to TaskNotFound
category: correctness
severity: medium
source: redteam
date: 2026-06-19
---

## What happened
`_A2A_CODE` in `app.py` mapped `404 → -32001` (TaskNotFound). Any unknown `/v1/` route that FastAPI could not match returned the TaskNotFound A2A code, misleading conforming consumers into treating a routing miss as a missing task. In practice, task-not-found is raised explicitly by task routes via `a2a_error(A2A_TASK_NOT_FOUND)`; a bare 404 on `/v1/` always means "no such route".

Additionally, `405 → -32004` is asymmetric with the forward `A2A_HTTP_STATUS` map where `-32004` maps to 501 (capability absent). The asymmetry is intentional (FastAPI emits 405 for wrong-method, not 501), but must be documented or it appears to be a bug.

## Fix
Remove `404` from the reverse `_A2A_CODE` map entirely. The `.get(status_code, -32603)` fallback already handles it with the generic server-error code. Document the 405/-32004 asymmetry with a comment explaining that HTTP method mismatch differs from capability absence.

## Check
grep -n '404.*-32001\|-32001.*404' agent_sdk/app.py
# Must return no results — 404 must NOT be mapped to -32001 in the reverse map.

## Prevention
In any reverse HTTP→JSON-RPC error map:
1. Only map HTTP codes that have a 1:1 semantic equivalent in the A2A spec.
2. Never map a generic routing failure (404 from framework route matching) to a domain-specific error code (TaskNotFound).
3. Domain-specific errors must be raised explicitly by the relevant route handler, not inferred from the HTTP status in the exception handler.
4. Asymmetries between forward and reverse maps must be documented with a spec citation or rationale comment.
