---
id: LRN-057
title: uv sync extra flags are not additive across invocations
category: ops
severity: high
source: redteam
date: 2026-06-15
---

## What happened
The upgrade skill's reinstall step for obo agents ran `uv sync --frozen --extra obo`, omitting `--extra dev`. Because pytest, pytest-asyncio, and httpx are declared only in the `[dev]` extra, they were never installed. The immediately-following `pytest -q` step then failed on every obo-extra agent.

## Root cause
`uv sync` installs exactly the extras named in that single invocation; it does not merge with any previously installed extras. Specifying `--extra obo` alone silently drops `[dev]` dependencies even though they were present before the sync.

## Check
grep -n 'uv sync' harness/skills/upgrade/SKILL.md | grep -v '\-\-extra dev' — any match that also contains '--extra obo' (or any other feature extra) without a paired '--extra dev' flag is a violation.

## Prevention
When planning any `uv sync` step that targets a feature extra (obo, azure, etc.), always include `--extra dev` in the same invocation so the post-install test gate has pytest available. Template: `uv sync --frozen --extra dev --extra <feature>`.
