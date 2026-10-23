---
id: LRN-469
title: MCP tools/call ignores advertised outputSchema on type mismatch
category: protocol
severity: high
source: protocol-audit
date: 2026-10-23
---

## What happened
In agent_sdk/routes/mcp.py (GH-225), a tool declared emits=(A,B) returning an unrelated BaseModel C gave isError:false with no structuredContent. A single-class emits=A returning C gave structuredContent that does not match A's outputSchema. tools/list had advertised an outputSchema in both cases.

## Root cause
match_emits() returning None silently skipped the branch, and the coercion path only ran for non-BaseModel results, so a wrong BaseModel type was never checked.

## Check
Run a test that validates every tools/call structuredContent against the tools/list outputSchema with jsonschema, including mismatched-model cases. Mismatches must return isError:true.

## Prevention
When planning any change to MCP result building, require: if outputSchema is advertised, a successful result carries conforming structuredContent, otherwise isError:true. Keep the MCP mismatch behaviour aligned with the A2A runner.
