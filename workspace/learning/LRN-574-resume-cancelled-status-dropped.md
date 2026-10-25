---
id: LRN-574
title: Resume handler drops protocol cancelled status
category: security
severity: high
source: redteam
date: 2026-10-25
---

## What happened
The GH-274 rewrite of agent_sdk/example/agent.py read only `payload.decision`. An AG-UI resume `{"status": "cancelled", "payload": {"decision": "approved"}}` (both accepted by ag_ui.py) now publishes the note; before, status "cancelled" declined it.

## Root cause
Narrowing the handler to payload.decision discarded the top-level `status`, so a cancelled interrupt ran the side effect.

## Check
Run a test in tests/test_gh235_nested_json_and_resume.py: resume with status "cancelled" and payload.decision "approved" must return {"published": False, ...}. Also grep the example for `parse_decision` or `"cancelled"`.

## Prevention
When planning resume-handler changes, require reject-wins handling (use `contrib.action_gate.parse_decision`) so `cancelled` always denies, and require a cancelled+approved test, not only status-only payloads.
