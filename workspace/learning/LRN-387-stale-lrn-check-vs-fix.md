---
id: LRN-387
title: Existing LRN Check clause contradicts a landed fix
category: protocol
severity: high
source: redteam
date: 2026-10-15
---

## What happened
LRN-049's Check said `allows()` must emit domain types freely and never suppress on catalog membership. GH-180 made `allows()` gate domain types on `self.catalogs`, so the Check failed against landed code and the next redteam round (Dimension 7) would flag GH-180 as a violation and push to revert it.

## Root cause
The fix changed a rule asserted by an existing LRN, but that LRN's Check and Prevention were not updated in the same change.

## Check
Read LRN-049: the AG-UI "emit freely" rule must live only in `for_custom_emit()` (returns self for tier "none", else core+extended with `any_catalog=True`). Confirm it cites GH-180 and the pin `tests/test_gh180_a2a_catalog_negotiation.py::test_custom_emit_ignores_declared_catalogs`.

## Prevention
When planning a fix that changes a rule, grep `workspace/learning/` for the symbol or rule and update every LRN Check/Prevention it contradicts in the same todo, citing the new issue and a pinning test.
