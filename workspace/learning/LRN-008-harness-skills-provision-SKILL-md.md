---
id: LRN-008
severity: high
title: Source health check uses GET /admin/api/overview, not a per-source POST endpoint
---

## Observation

Phase 3 step 10 of `harness/skills/provision/SKILL.md` instructs callers to `POST /admin/sources/<source_name>/health` and expect `{"status": "ok"}`. No such endpoint exists in the SDK. An exhaustive grep of `agent_sdk/routes/admin.py` confirms there is no per-source POST health route. The correct mechanism is `GET /admin/api/overview`, which returns a `sources[]` array where each entry carries a `healthy: true/false` field populated by the adapter's own `health_check()` method. The incorrect instruction causes provision to fail silently or error when it attempts the invented probe.

## Root Cause

The SKILL.md author assumed a per-resource POST health endpoint (a common REST pattern) without cross-checking the actual admin router. The real health signal is embedded in the overview response rather than exposed as a dedicated per-source route, which is non-obvious and was not documented at the point the skill was written.

## Prevention

Before documenting any SDK endpoint in a skill or harness file, grep `agent_sdk/routes/` to confirm the route exists and note the exact HTTP method, path, and response schema. Per-source health is surfaced through `GET /admin/api/overview` (`sources[].healthy`), not through per-source POST endpoints — there is no `POST /admin/sources/<name>/health` route.
