---
id: LRN-144
title: New model-client constructor kwarg added without settings field or seam wiring
category: sdk
severity: high
source: redteam
date: 2026-08-15
---

## What happened
GH-133 added `max_retries`/`timeout` support intended to fix sustained-throttling
failures, but `Agent._build_model_client()` in `agent_sdk/app.py` still constructs
`OpenAIModelClient(...)` without them. No `BaseAgentSettings` field or env var
exposes them, so every settings-driven deployment silently keeps the openai
SDK's default `max_retries=2` and the original bug is unchanged.

## Root cause
The fix added constructor support but never plumbed it through the settings
layer to the one call site that builds the client, and no test asserted the
value reaches the constructed client.

## Check
Verify that `agent_sdk/config.py` defines `openai_max_retries` and
`openai_timeout` fields, and grep `app.py` for `_build_model_client` to confirm
both are forwarded to `OpenAIModelClient(...)` at the construction call site.

## Prevention
When planning a fix that adds a new constructor/client kwarg, require a
matching `BaseAgentSettings` field (with env alias) AND an integration test at
the `_build_*` seam asserting the settings value reaches the constructed
object — a kwarg without both is dead configuration and the issue stays open.
