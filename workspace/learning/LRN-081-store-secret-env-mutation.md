---
id: LRN-073
title: Store-sourced credential written to os.environ leaks to subprocesses
category: security
severity: high
source: redteam
date: 2026-06-15
---

## What happened
`agent_sdk/agent/bedrock.py` resolved a Bedrock bearer token from the credential
store and then wrote it into the global process environment via
`os.environ["AWS_BEARER_TOKEN_BEDROCK"] = self._bearer_token`. The value is never
cleaned up, so it persists for the full process lifetime and is inherited by every
subprocess spawned afterward — re-introducing the same env-leak risk the store was
designed to prevent.

## Root cause
The credential store eliminates SI-6 leaks at the source, but writing a resolved
secret back into `os.environ` widens the blast radius to child processes and any
code that inspects the environment (logging, debug tooling, subprocess shells).
Scoping was not applied after retrieval.

## Check
```bash
grep -n 'os\.environ\[.*TOKEN\|os\.environ\[.*SECRET\|os\.environ\[.*KEY\|os\.environ\[.*PASSWORD' \
  agent_sdk/agent/bedrock.py
```
Confirm zero matches, or that any match is wrapped in a `try/finally` that pops the
key. Also verify a test asserts `"AWS_BEARER_TOKEN_BEDROCK" not in os.environ` after
the client is constructed.

## Prevention
When planning any provider integration that resolves a credential from the store,
ensure the secret is scoped to the SDK client/session object only — pass it via a
`botocore.session.Session`, client constructor kwarg, or a temporary env context
manager with `finally`-pop. Never assign store-resolved secrets to `os.environ`
directly; doing so negates the isolation the store provides.
