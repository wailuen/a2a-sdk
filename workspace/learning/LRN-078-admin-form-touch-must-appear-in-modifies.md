---
id: LRN-078
title: Admin-form field additions must appear in the todo Modifies: list
category: harness
severity: medium
source: redteam (RT-003, w021)
date: 2026-06-19
---

## What happened

GH-72 added a fourth Bedrock credential field (`aws_session_token`) to
`routes/admin.py` as part of wiring STS / temporary credential support. The
todo's `Modifies:` list declared only `agent_sdk/app.py` and
`agent_sdk/agent/bedrock.py`. `admin.py` appeared in `Reads:` (correctly — it
was read during planning) but not in `Modifies:`. Per LRN-053, wave scope is
derived from `Creates: ∪ Modifies:`; an undeclared modified file escapes
scope-based redteam entirely.

## Pattern

**Admin-form touch invisible to scope** — when a credential field is added to
a backend model (`BedrockModelClient.__init__`) and wired in `app.py`, the
corresponding admin UI change in `routes/admin.py` is a natural co-change that
can be overlooked in the `Modifies:` list because it is "just UI."

## Root cause

The todo was authored with the backend files in scope; the admin-form extension
was added during implementation without updating the scope declaration. Because
`admin.py` was already listed under `Reads:`, the oversight was invisible —
the file appeared in the todo, just under the wrong key.

## Check

When a credential backend (model client, source adapter) gains a new
parameter, check whether `routes/admin.py` (or any other admin/config form)
declares that credential namespace. If yes, `routes/admin.py` must appear in
`Modifies:` and the AC bullets must cover the new form field and its
behaviour (secret flag, required flag, conditional omission in downstream
calls).

```bash
grep -n "aws_session_token\|_BEDROCK_FIELDS" \
  agent_sdk/routes/admin.py \
  agent_sdk/agent/bedrock.py \
  agent_sdk/app.py
```

All three files must show the field; if admin.py has it but is absent from
`Modifies:`, the todo is out of scope.

## Prevention

When planning any todo that adds a credential field to a backend construct
inside a registered credential namespace:

1. Check whether that namespace has an admin form entry in `routes/admin.py`.
2. If yes, add `agent_sdk/routes/admin.py` to `Modifies:` at planning time,
   not after implementation.
3. Add AC bullets for: (a) the new `CredentialField` in the admin form,
   (b) the credential read in `app.py` / adapter, and (c) conditional omission
   when the field is unset (e.g. STS token omitted for long-lived IAM keys).
