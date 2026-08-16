---
id: LRN-140
title: Base-class security contract fixed on 2/14 subclasses, no completeness gate
category: security
severity: high
source: redteam
date: 2026-08-15
---

## What happened
GH-130's delimiter-safety fix (sanitize before `" | "`/`"\n"` joins) landed on only the two
renderers named in the report (`ComparisonTable`, `EntityList`), though `ContentModel`'s
docstring binds the contract to every subclass. 10+ other renderers stayed unsanitized until
fixed separately; nothing catches a future renderer skipping the sanitizer.

## Root cause
The AC named only the report's instances; the contract never became a completeness gate.

## Check
`grep -n "__subclasses__" tests/test_content_types.py` must match a meta-test over
`ContentModel.__subclasses__()` failing any `to_plain_text()` that joins on a delimiter
without calling the sanitizer.

## Prevention
Scope base-class-contract fixes to "all subclasses via an enumerating meta-test," not the
named instance(s) in the report.
