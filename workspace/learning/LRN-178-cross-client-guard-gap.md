---
id: LRN-178
title: Cross-client invariant lapses when fixed in only one model client
category: sdk
severity: high
source: redteam
date: 2026-08-15
---

## What happened
LRN-104 Layer 3 (`except ModuleNotFoundError: raise` above a broad catch-all
in a model client's invoke path) exists in `openai_client.py:121` but was
missing from `bedrock.py`, whose `converse()` catch-all sits above
`_boto_client()`'s deferred boto3/botocore imports.

## Root cause
The guard was added only to the client behind the original incident, never
propagated to sibling clients, including a second `except Exception` added
later inside `_boto_client()`.

## Check
`grep -n "except Exception" agent_sdk/agent/*.py` — for each match in an
invoke/construction path, confirm `except ModuleNotFoundError: raise`
precedes it in the same `try` block, per client.

## Prevention
When adding a deferred import or broad `except` to one model client, require
the guard (plus a test) across every `agent_sdk/agent/*.py` file with
deferred imports.
