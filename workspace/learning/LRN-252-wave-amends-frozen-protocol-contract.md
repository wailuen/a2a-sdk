---
id: LRN-252
title: Wave resolved one contract divergence by deletion and an identical one by widening the frozen spec
category: protocol
severity: high
source: redteam
date: 2026-09-03
---

## What happened
The same wave hit two instances of a field not covered by the frozen A2UI Standard
Profile v1 contract. For `FundPerformance.fund_name` it deleted the field (GH-149).
For `TimeSeriesChart.metadata` — frozen as a typed sub-shape — it instead edited the
frozen tables in all three advisor copies to make `metadata` free-form `dict[str,
Any]` on every type, plus a directive telling conformance audits not to flag it.

## Root cause
No versioned-extension mechanism exists for fields outside the frozen contract (the
exact gap GH-149 cites), so the wave improvised two opposite, self-authorized
resolutions to the same underlying gap instead of treating either as a spec
amendment requiring sign-off.

## Check
`grep -rn "MUST NOT flag a type for having or lacking" .claude/agents/a2ui-advisor.md
harness/agents/a2ui-advisor.md` — any such directive, or a frozen-table `metadata`
type change, must trace to a REVIEWS.md sign-off entry, not a wave's own commit.

## Prevention
When planning a wave, flag any edit to a frozen protocol contract table (Standard
Profile field types, catalog shapes) as requiring explicit user ratification before
merge — treat two instances of the identical divergence resolved in opposite
directions within one wave as the signal that the rule is being bent, not the code.
