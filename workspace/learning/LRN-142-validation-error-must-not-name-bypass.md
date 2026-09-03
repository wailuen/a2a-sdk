---
id: LRN-142
title: Reuse-mismatch error text names its own bypass token to the model
category: security
severity: high
source: redteam
date: 2026-09-02
---

## What happened
`resolve_reuse_fields`'s rejection message (reuse.py:464) tells the model to prefix a value with `$raw:` to bypass the mismatch check. A model that hallucinated a wrong id can resubmit `$raw:<same id>` and execute it, reducing GH-148's only correctness gate to a speed bump.

## Root cause
The error text was written to be informative to the model rather than adversarial-safe — it exposes an operator-only escape hatch to the exact caller the check exists to constrain.

## Check
`grep -n '\$raw:' agent_sdk/agent/reuse.py` — the mismatch-rejection string must not mention `$raw:`. `tests/test_gh148_reuse_kind_substitution.py::test_mismatch_error_names_the_raw_override_escape_hatch` must be replaced with a test proving a rejected raw value cannot be re-executed via `$raw:`.

## Prevention
When planning a validation gate whose only adversary is the model itself, forbid the rejection message from naming its own bypass syntax. Any escape hatch must be a separate operator/registration-time opt-in flag (e.g. `allow_raw_override=False` default), never a token surfaced to the caller being validated.
