---
id: LRN-009
title: Anthropic model backend documented as functional but unimplemented in the SDK
category: docs
severity: high
source: redteam
date: 2026-06-14
---

## Observation

setup/SKILL.md Phase 0 step 5 and Phase 3 step 5 fully document "Anthropic" as a working model backend, including an `ANTHROPIC_MODEL` env var (e.g. `claude-opus-4-5`) and a credential seeding path via `PUT /admin/api/credentials/__model__/anthropic_api_key`. sdk-advisor.md repeats the same claim at lines 65-68. The SDK has no `ANTHROPIC_MODEL` / `anthropic_model` config field in `BaseAgentSettings` (agent_sdk/config.py), no Anthropic code path in `_build_model_client` (agent_sdk/app.py lines 135-165), and admin.py line 103 explicitly marks `anthropic_api_key` as "Reserved for future Anthropic model-backend support." Following the documented instructions produces a broken agent that cannot boot with the Anthropic backend.

## Root Cause

Documentation was written speculatively — describing the intended end-state of a feature rather than what is implemented. No process enforced that every documented backend option must have a corresponding live code path before the docs ship.

## Prevention

Only document model backends that have a live code path in `_build_model_client` and a corresponding config field in `BaseAgentSettings`. When a backend is reserved/unimplemented, add an explicit notice in the docs: "NOT YET IMPLEMENTED — reserved for a future release. Do not configure." Remove or gate the notice when the implementation lands.
