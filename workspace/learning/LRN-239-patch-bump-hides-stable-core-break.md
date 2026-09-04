---
id: LRN-239
title: Voluntary stable-core break shipped under a patch version bump
category: ops
severity: high
source: redteam
date: 2026-09-03
---

## What happened
`agent_sdk/models/content_types.py` hoisted a new `metadata` field
onto `ContentModel` and split `to_plain_text()` into a new abstract
`_body_text()`, changing wire field order for all 14 frozen Profile
types and hard-failing external subclasses that already define
`metadata`. None of this is required by an external protocol spec,
yet it shipped as `pyproject.toml` version `0.5.45` — a patch bump —
contrary to DESIGN.md §4.0's rule that a voluntary breaking change to
the stable core requires a major bump.

## Root cause
The wave cited DESIGN.md §4.0's wire-conformance exemption without
verifying the exemption's condition (spec-driven change) actually
held for this diff.

## Check
For any CHANGELOG entry under a `🔴 Breaking changes` heading, confirm
it cites the specific external spec clause forcing the change, or the
version bump is major/minor per DESIGN.md §4.0 — not patch.

## Prevention
When planning a release touching a FROZEN Profile type or a public
ABC's abstract method set, require an explicit DESIGN.md §4.0
citation naming the external spec clause before allowing a patch
bump; absent that citation, plan the change under a major/minor bump
or split it out of the release.
