---
id: LRN-179
title: Exemption citations must be verified against file location, not asserted
category: ops
severity: high
source: redteam
date: 2026-08-15
---

## What happened
GH-134's CHANGELOG entry cited DESIGN.md §4.0's exemption, claiming
`ToolDecl.annotations` lives under `models/`; it's actually in
`agent_sdk/agent/registry.py`. Round 8's two-condition test (`models/`
location AND spec-conformance-driven) disqualified sibling GH-135, but the
`models/` check was skipped for GH-134, cleared on spec-conformance alone.

## Root cause
The `models/` condition was accepted on prose, not checked against the
actual file location.

## Check
`grep -B2 -A6 "wire-shape conformance exemption" CHANGELOG.md` — confirm
each cited type is actually defined under `agent_sdk/models/`.

## Prevention
When planning a CHANGELOG entry invoking a multi-condition exemption,
require every condition checked against the landed file path, not the
entry's own prose — apply a sibling's disqualifying test here too.
