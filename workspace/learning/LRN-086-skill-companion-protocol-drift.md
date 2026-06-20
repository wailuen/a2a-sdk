---
id: LRN-086
title: Companion SKILL.md re-documents broken wire protocol after workflow fix
category: protocol
severity: high
source: redteam
date: 2026-06-19
---

## What happened
acceptance/SKILL.md (the caller docs for acceptance-api.js) still documented the pre-GH-71 broken protocol: A2A via POST /v1/message/stream (slash) wrapped in a JSON-RPC envelope, AG-UI via POST /run, no messageId field, and a deterministic threadId. The workflow file was fixed but the companion SKILL.md was not updated in the same change, re-introducing all four GH-71 protocol bugs and the LRN-040 concurrent-run contamination for any caller following the docs.

## Root cause
The fix was applied only to the workflow .js file; the companion SKILL.md was not treated as part of the same atomic change, leaving the caller documentation frozen at the pre-fix wire contract.

## Check
```bash
grep -n 'message/stream\|/v1/message/stream\|jsonrpc\|method.*stream\|POST /run' \
  harness/skills/acceptance/SKILL.md
```
Must return no matches. Also verify:
```bash
grep -n 'messageId' harness/skills/acceptance/SKILL.md
```
Must return at least one match (messageId documented as required).

## Prevention
When planning a fix to any workflow .js file that changes an endpoint path, HTTP method, envelope format, or required field, ensure the companion SKILL.md is updated in the same commit. Treat SKILL.md as part of the wire contract — not optional documentation.
