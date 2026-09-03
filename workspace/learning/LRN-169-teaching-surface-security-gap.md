---
id: LRN-169
title: Security contract documented on private docstring, not public authoring guide
category: security
severity: high
source: redteam
date: 2026-08-15
---

## What happened
GH-130's delimiter-safety contract was written into `ContentModel.to_plain_text()`'s
private docstring only. `docs/content-types.md` — the public guide domain-card
authors actually read — still shows a `to_plain_text()` example that interpolates
untrusted fields raw, with no mention of `safe_error_text`/sanitisation.

## Root cause
The GH-130 AC ("document the delimiter-safety contract") was satisfied on the
SDK internal surface but never propagated to the teaching surface, so every
author following the doc's example re-introduces the vulnerability.

## Check
`grep -n "to_plain_text" docs/content-types.md` — confirm a "Delimiter safety"
subsection exists near the domain-card example and the sample implementation
calls `safe_error_text`/`safe_block_text` rather than raw f-string interpolation.

## Prevention
When planning any change that adds a security contract to an SDK extension
point (base class, hook, protocol callback), require a doc-sync task against
every public authoring guide for that extension point — a docstring-only fix
is incomplete; grep `docs/` for the same method/pattern name before closing.
