---
id: LRN-135
title: Portable spec oracle rewritten to teach SDK-private deviation as canonical rule
category: protocol
severity: high
source: redteam
date: 2026-07-25
---

## What happened
The GH-128 fix rewrote the portable, project-agnostic `a2ui-advisor.md` oracle
(~lines 729-733, 785-787, 865-867) to state this SDK's invented `data.messages`
wrapper as THE A2UI-over-A2A rule, with zero acknowledgment that A2UI v0.9.1's
own A2A binding mandates a bare array (LRN-134's citation trail confirms this).

## Root cause
The fix conflated "what this SDK does" with "what the spec says" inside a
shared audit reference explicitly scoped to audit arbitrary third-party
projects against the published spec, never this codebase's own output.

## Check
In `~/.claude/agents/a2ui-advisor.md`, the `DataPart.data` shape rule must
state the bare-array binding as canonical (citing A2UI v0.9.1 spec text);
`data.messages` may appear only inside a clearly labeled "this SDK's
non-canonical deviation" callout, never as the rule the audit enforces.

## Prevention
When planning a fix that touches a portable/project-agnostic advisor or
check-skill spec reference, add an explicit review step confirming the diff
encodes the published spec text (with citation), not the current codebase's
output — implementation deviations get their own labeled non-canonical
section, and must never overwrite the canonical rule they deviate from.
