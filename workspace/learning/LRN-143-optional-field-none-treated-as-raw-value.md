---
id: LRN-143
title: Optional ReuseKind field permanently rejects explicit None as a raw mismatch
category: sdk
severity: high
source: redteam
date: 2026-09-02
---

## What happened
`ReuseKind` documents `<scalar> | None` as a supported field shape, but `resolve_reuse_fields` (reuse.py:403) treats an explicit `None` argument as a raw value to check against prior resolutions. Once any resolution of that kind exists, `None != "ENT_1"` fails the match and the tool becomes permanently uncallable with the field omitted — `$raw:` cannot recover it either, since it yields `""`, not `None`.

## Root cause
The field loop has no early exemption for `None`; it falls through into the same raw-vs-resolved equality gate used for real scalar values.

## Check
`grep -n "raw is None" agent_sdk/agent/reuse.py` should show a `continue` before the `$raw`/`$ref` branches (reuse.py:403-406). Add a regression test: `Annotated[str | None, ReuseKind("entity_id")] = None` called with `{"entity_id": None}` while `index` holds a prior resolution of that kind — must resolve with `error is None`.

## Prevention
When planning a raw-value validation gate on an `Optional`/`| None` field, require an explicit `None`-is-not-a-raw-value exemption as a named acceptance criterion — a field's declared "not supplied" sentinel must never be run through the same equality contract as a real value.
