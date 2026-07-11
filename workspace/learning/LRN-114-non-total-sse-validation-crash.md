---
id: LRN-114
title: Non-total content extraction crashes AG-UI SSE stream without terminal frame
category: protocol
severity: high
source: redteam
date: 2026-07-11
---

## What happened
`_validate()` in `agent_sdk/routes/ag_ui.py` joined multimodal `content`
`text` fields via `"".join(...)` without coercing non-strings. A
`text: null`/int part raised uncaught `TypeError`, aborting `/ag-ui/run`'s
SSE stream right after `RUN_STARTED`/`STATE_SNAPSHOT` with no terminal
frame — breaking AG-UI's one-terminal-frame invariant.

## Root cause
The join was a happy-path extractor, not total over its input type, and
its call site wasn't reliably inside the try/except that maps exceptions
to a terminal `RUN_ERROR` frame.

## Check
Verify functions joining client `content.text` fields in `ag_ui.py` coerce
non-strings (`str(p.get("text") or "")`, never raw concat) and run only
inside the SSE try/except. Test: POST `content:[{"type":"text",
"text":null}]` (and int); assert one terminal frame, not a truncated
stream.

## Prevention
When planning SSE handler changes, require every function called after
RUN_STARTED be total over its input type, or sit strictly inside the
exception-to-terminal-frame try/except.
