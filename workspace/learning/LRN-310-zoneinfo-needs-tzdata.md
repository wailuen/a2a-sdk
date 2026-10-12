---
id: LRN-310
title: Default-on ZoneInfo use without tzdata breaks boot
category: ops
severity: high
source: redteam
date: 2026-10-11
---

## What happened
The new default-on `timezone` validator (config.py ~263-275) runs `ZoneInfo('UTC')` on every BaseAgentSettings build, even with AGENT_SDK_INJECT_CURRENT_DATE=false. pyproject.toml has no `tzdata` dependency. With no system zone files (Windows, Alpine, distroless) every agent fails to boot, and the error blames the operator's zone name. Reproduced via `zoneinfo.reset_tzpath([])`.

## Root cause
Code assumed system IANA zone data exists; earlier rounds deferred it as medium.

## Check
grep pyproject.toml for `tzdata`. Verify a test that calls `zoneinfo.reset_tzpath([])` then builds default BaseAgentSettings without error.

## Prevention
When planning a default-on feature using zoneinfo, add `tzdata` to dependencies or a UTC fast path (datetime.timezone.utc), and skip validation when the feature is off. Treat boot-blocking defaults as high.
