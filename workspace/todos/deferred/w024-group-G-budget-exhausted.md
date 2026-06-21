# Deferred: w024 G — budget exhausted

- **Wave ID:** w024
- **Group:** G
- **Date:** 2026-06-20
- **Rounds completed:** 5 (budget exhausted) + follow-up fix 2026-06-21
- **Status:** All findings resolved — wave complete

---

## Instruction

~~Fix remaining findings, then re-run `/wave w024`.~~

All findings below were resolved in a follow-up pass on 2026-06-21. No further
action required.

---

## Findings

### RT-001 — medium — FIXED (2026-06-21)
**File:** `agent_sdk/config.py:175`

**Fix applied:** Added `is_placeholder_name -> bool` property to
`BaseAgentSettings` as the single source of truth for the
placeholder-or-blank predicate. All three former hand-rolled instances
(`app.py:_check_agent_name`, `config.py:display_name`,
`agent_card.py:build_agent_card`) now delegate to it. The three
`PLACEHOLDER_AGENT_NAME` imports in `app.py` and `agent_card.py` were
removed; `config.py` retains the constant as a module-level definition
(still referenced by `is_placeholder_name`).

---

### RT-002 — low — FIXED (2026-06-21)
**File:** `agent_sdk/app.py:541`

**Fix applied:** `app_title` now uses `settings.display_name` instead of
the raw `settings.agent_name.strip() or PLACEHOLDER_AGENT_NAME` expression.
OpenAPI/docs title is now normalized consistently with health, MCP
serverInfo, and the agent card — the placeholder `"agent"` is never
advertised on any title-bearing surface, including DEV_MODE.
