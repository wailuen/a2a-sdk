---
id: LRN-077
title: Dependency floor too low — mocked tests hide AttributeError on permitted versions
category: sdk
severity: critical
source: redteam
date: 2026-06-19
---

## What happened
`agent_sdk/agent/bedrock.py` calls `botocore.tokens.ScopedEnvTokenProvider` (added in botocore 1.39 / boto3 1.39.0), but `pyproject.toml` pins `boto3>=1.34`. Any consumer on boto3 1.34–1.38 — all valid per the declared floor — crashes with `AttributeError: module 'botocore.tokens' has no attribute 'ScopedEnvTokenProvider'` on the first bearer-token Bedrock call. The 18 GH-72 tests pass because they monkeypatch the provider, so the real attribute is never accessed under an old botocore.

## Root cause
The dependency lower bound was not raised when new botocore symbols were introduced; mocked unit tests that patch the symbol at import time masked the incompatibility with the permitted version range.

## Check
`grep -n 'boto3' agent_sdk/pyproject.toml` — confirm `boto3>=1.39`; also run `python -c "import botocore.tokens; botocore.tokens.ScopedEnvTokenProvider"` in a clean env at the declared floor to verify no AttributeError.

## Prevention
When planning any feature that calls a vendor API symbol introduced in a recent library release, raise the dependency lower bound in pyproject.toml to that release in the same wave unit. Add a non-mocked import test (`assert hasattr(botocore.tokens, 'ScopedEnvTokenProvider')`) so a stale pin fails CI before consumers are affected.
