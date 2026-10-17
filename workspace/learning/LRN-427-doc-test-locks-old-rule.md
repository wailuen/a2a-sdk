---
id: LRN-427
title: Substring doc test can lock in a reversed rule
category: testing
severity: high
source: redteam
date: 2026-10-17
---

## What happened
tests/test_gh117_mcp_transport_split_docs.py::test_design_md_streamable_http_absent_header_returns_400 still required DESIGN.md to say absent-header requests return 400. It passed only because the GH-200 history note ("reverses GH-77's absent→400") put "400" inside the 300-character window.

## Root cause
The test was not updated when GH-200 reversed the rule. A substring window assertion can match reversal wording and keep enforcing the old rule.

## Check
Verify `grep -n "returns_400\|absent header → 400\|now 400s" tests/test_gh117_mcp_transport_split_docs.py` has no Streamable HTTP match. The test must assert GH-200, negotiated and 2025-03-26, plus a negative check that Streamable HTTP does not "400 on absent".

## Prevention
When planning a rule reversal, include the doc-conformance tests (test_gh117_*, LRN check tests) in the grep sweep. Assert the new rule positively and the old rule negatively, never by a loose substring window.
