---
id: LRN-209
title: 429 tests assert status_code only, missing headers and body redaction
category: testing
severity: high
source: redteam
date: 2026-08-19
---

## What happened
`tests/test_gh143_mcp_get_stream_cap.py` and `tests/test_rt001_mcp_sse_stream_cap.py`
assert `status_code == 429` on every rate-limit branch but never assert
`Retry-After`, never assert `MCP-Protocol-Version` on mcp_get's rejections, and
never confirm the 429 body/logs omit the identity value used to key the limit —
an SI-2 requirement in the source todo.

## Root cause
A test that only checks the HTTP status code treats "correct error class" as
"correct error response" — it doesn't exercise the headers or body that carry
the contract's other literal requirements (retry timing, protocol version,
identity redaction).

## Check
`grep -n "status_code == 429" tests/test_gh143_mcp_get_stream_cap.py
tests/test_rt001_mcp_sse_stream_cap.py` and confirm every matched test also
asserts `r.headers['Retry-After']`, asserts `MCP-Protocol-Version` presence
(or documents its deliberate absence), and asserts the identity subject/token
appears in neither `r.text` nor caplog.

## Prevention
When planning any wave adding a rate-limit/error-status response on a
protocol route, require the todo to name assertions for every header the
route emits on that status (not just the status code) and, if the AC is
SI-tagged for redaction, a test that mints a recognizable identity value and
asserts its absence from both response body and logs.
