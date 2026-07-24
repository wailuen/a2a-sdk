---
id: LRN-038
title: "→ Consolidated into LRN-034 (unconditional seam audit dispatch)"
category: testing
severity: high
source: redteam
date: 2026-06-15
superseded_by: LRN-034
---

## Redirect

This learning has been consolidated into **[LRN-034](LRN-034-unconditional-seam-audit-no-guard.md)**.

LRN-038 originally codified the "seam audit dispatches unconditionally" invariant from the
A2UI-only-wave angle (an A2UI-only wave burning an extra agent call on a vacuous seam audit).
After the w036/GH-123/LRN-132 reversal (2026-07-21) — which REMOVED the `seamPaths.length > 0`
guard so an `AUTH_SURFACE`-only wave still dispatches the seam leg — LRN-034 and LRN-038 asserted
the identical invariant with byte-identical README index descriptions and near-identical Check
clauses. To eliminate the duplicate index row and the redundant Check clause, the two were merged
into LRN-034 (the lower ID, kept canonical); LRN-038's unique content (the "name ALL FOUR runners"
admonition, the `test_workflow_sync.py` byte-identity note, and the "mirror across all copies"
prevention) was folded into LRN-034.

The ID is retained as this stub so existing cross-references (LRN-027, the wave-cycle.js inline
comments) do not dangle. Do NOT re-add a `seamPaths.length > 0` guard — see LRN-034, plus
LRN-066/LRN-131 on the oscillation risk of reverting an intentionally-reversed decision.
