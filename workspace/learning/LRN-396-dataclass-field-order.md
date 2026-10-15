---
id: LRN-396
title: New field inserted mid-dataclass shifts positional args
category: sdk
severity: high
source: redteam
date: 2026-10-15
---

## What happened
`Identity.service` was added between `admin` and `label`/`user` in the exported frozen dataclass. `Identity("api_key", sid, False, "my-label")` then set service="my-label", which is truthy, so require_identity let the key through even with idp_disable_api_keys on. CHANGELOG also did not list the new public field.

## Root cause
A privilege flag was inserted mid-dataclass instead of last or keyword-only.

## Check
Verify `service` is the last field or `kw_only=True` in agent_sdk/auth/identity.py. Run a test building Identity positionally in the old field order and assert service is False. Confirm CHANGELOG Added names Identity.service.

## Prevention
New fields on exported dataclasses in agent_sdk.auth go last or keyword-only, default safe, with a positional-compat test.
