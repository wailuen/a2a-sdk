---
id: LRN-302
title: Wave must not redefine a cost limit from an AC without a ruling
category: sdk
severity: high
source: redteam
date: 2026-10-11
---

## What happened
GH-155 AC said the budget-exit summary may spend at most `final_summary_max_tokens` beyond the budget. The wave capped only summary OUTPUT and wrote that meaning into the docstring, DESIGN.md and CHANGELOG. The maintainer ruling on GH-155 does not cover it.

## Root cause
The wave re-signed its own policy change (LRN-251 pattern); a docstring was treated as a ruling.

## Check
Verify every change to the meaning of a limit in `agent_sdk/agent/loop.py` (output-only vs total tokens) cites a maintainer ruling URL in the todo or GH issue. grep DESIGN.md/CHANGELOG for "not charged"/"input" wording and confirm a matching ruling link.

## Prevention
When planning work that touches a cost or limit stated in an AC, implement it as written. If the AC seems infeasible, add an escalation task and record the maintainer ruling URL before the wave runs.
