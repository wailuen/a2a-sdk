---
id: LRN-426
title: Ruling reversal must sweep every doc, not only the named one
category: protocol
severity: high
source: redteam
date: 2026-10-17
---

## What happened
GH-200 reversed the GH-77 rule (Streamable HTTP absent MCP-Protocol-Version no longer 400s). The w056 todo's doc AC named only DESIGN.md, so REVIEWS.md (Round-1 MCP table row 11, and the "absent→400" line in the Round-1 notes) kept the old rule. This repeated the drift LRN-118 records.

## Root cause
The todo AC listed one doc; nobody grepped all docs for the old rule.

## Check
Verify no doc claims Streamable HTTP 400s on absent header: `grep -nE "non-init.{0,6}400|absent.{0,3}400" REVIEWS.md DESIGN.md` must show no Streamable HTTP match (GH-200 history notes aside). Run tests/test_gh117_mcp_transport_split_docs.py::test_reviews_md_round1_mcp_table_*.

## Prevention
When planning a ruling that reverses protocol behavior, require an AC that greps DESIGN.md, REVIEWS.md, LRN files and doc-guard tests for the old rule and updates all in the same commit. An AC naming only DESIGN.md is incomplete (LRN-118).
