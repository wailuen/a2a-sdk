---
id: LRN-414
title: Wave deviated from maintainer ruling without ratification
category: protocol
severity: high
source: redteam
date: 2026-10-17
---

## What happened
The maintainer ruling on GH-185 (and the todo AC) says `tasks/resubscribe` is bound to the resuming caller. The code (`a2a.py` resubscribe handler) and CHANGELOG skip it, because no tool runs on that path. The reasoning may be sound, but the wave decided and documented it itself.

## Root cause
The implementer treated a technical justification as authority to depart from a recorded ruling, with no escalation.

## Check
For each ruling URL cited in a todo, verify each AC is implemented as written (e.g. grep `bind_identity` in the `tasks/resubscribe` handler in `agent_sdk/routes/a2a.py`). Any departure must cite a ratifying GitHub issue comment URL.

## Prevention
When a todo cites a maintainer ruling, the planner must mark its ACs as non-negotiable. An implementer who wants to depart must escalate and record the user's approval URL before the wave, and CHANGELOG must not call the departure settled.
