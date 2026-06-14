---
id: LRN-007
severity: high
title: Bootstrap endpoint is POST /admin/api/keys not POST /admin/bootstrap
---

## Observation
`harness/skills/provision/SKILL.md` Phase 2 step 6 instructs callers to run `POST /admin/bootstrap` with the bootstrap token. The actual SDK endpoint is `POST /admin/api/keys` with the token supplied via the `X-Bootstrap-Token` request header (see `agent_sdk/routes/admin.py` line 234 and the docstring at line 14). No route named `/admin/bootstrap` exists anywhere in the SDK. An agent following these instructions will receive a 404 from the real server.

## Root Cause
The skill documentation was written with a guessed or placeholder endpoint name that was never validated against the actual route table in `agent_sdk/routes/admin.py`. The correct endpoint and header convention was already documented correctly in `harness/skills/setup/SKILL.md` (line 259: "Once `POST /admin/api/keys` has returned the first admin key"), but the divergence was not caught before the provision skill shipped.

## Prevention
All skill documents that reference SDK HTTP endpoints must cite the exact route as it appears in `agent_sdk/routes/`, and the `X-Bootstrap-Token` header usage must be documented consistently. When authoring or reviewing any skill that calls the bootstrap flow, cross-check the route name against `agent_sdk/routes/admin.py` and against `setup/SKILL.md` — the three must agree. The canonical rule: bootstrap endpoint is `POST /admin/api/keys` with the token in the `X-Bootstrap-Token` request header.
