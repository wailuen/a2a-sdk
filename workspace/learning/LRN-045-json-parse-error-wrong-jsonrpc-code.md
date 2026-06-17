---
id: LRN-045
title: JSON parse failure must return -32700, not -32602 (invalid-params)
category: protocol
severity: high
source: redteam
date: 2026-06-17
---

## What happened
When the agent received a request body that was not valid JSON, the error handler
emitted a JSON-RPC error with code -32602 (Invalid params). The correct code for
a malformed request that cannot be parsed is -32700 (Parse error). Clients that
inspect the error code to determine retry strategy would incorrectly treat an
unparseable body as a parameter problem and retry with modified params rather
than fixing the serialisation.

## Root cause
The JSON-decode try/except block fell through to the generic parameter-validation
error path, which always emits -32602. The parse-error case was never given its
own branch. The two error classes look similar from the outside (both produce
400-level behaviour) so the wrong code went undetected until wire-level testing.

## Check
```
grep -n '\-32602\|\-32700\|ParseError\|parse_error' agent_sdk/server/jsonrpc.py
# The JSON decode exception handler must emit code -32700.
# The -32602 code must only appear in the parameter-validation branch.
# Verify with: python3 -c "import requests,json; r=requests.post('<url>',
#   data='not json', headers={'Content-Type':'application/json'});
#   assert r.json()['error']['code'] == -32700"
```

## Prevention
When planning JSON-RPC server error handling, map the three top-level error
classes to their canonical codes before writing any handler: -32700 (parse),
-32600 (invalid request), -32602 (invalid params). Place the JSON decode
try/except as the outermost guard, returning -32700 on failure, before any
parameter-extraction or validation logic that could emit -32602.
