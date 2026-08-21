---
id: LRN-103
category: protocol
severity: medium
summary: A2A multi-turn continuation must use contextId, not taskId, for completed tasks
prevention: Harness/client multi-turn drivers must capture contextId from turn 1 and omit taskId on turns 2+ (unless prior task was input-required)
---

## What happened

Completed A2A tasks are terminal states. Sending a new `message/send` or
`message/stream` request that carries the original `taskId` returns JSON-RPC
error `-32004` (UnsupportedOperation, HTTP 501): the task exists but is
terminal, so `-32001`/404 (TaskNotFound) would misrepresent the failure as
"no such task." The server rejects the message because a task in a terminal
state cannot receive further input.

(Originally this learning recorded `-32001`/404 for both methods. GH-144
reconciled `message/stream` onto the same `-32004`/501 code `message/send`
had already used since `_resume_or_error` landed — see
`agent_sdk/routes/a2a.py`'s `message_stream`, guarded by
`tests/test_w017_gh51_multiturn.py::test_stream_terminal_taskid_returns_unsupported`.
`-32001`/404 is still correct, and still asserted by
`test_stream_terminal_taskid_foreign_identity_returns_not_found`, for the
distinct case of a **different identity's** terminal task — there the
identity-scoped lookup returns "not found" before the terminal check is ever
reached, so existence is never leaked across identities.)

The correct continuation key is `contextId`. The server assigns a `contextId`
on the first turn and that identifier persists for the lifetime of the
conversation regardless of how many tasks it spans. Subsequent turns must
supply `contextId` (and omit `taskId`, or supply a fresh client-generated
`taskId` for the new task) so the server can route the message into the right
conversation context.

## Correct pattern

```python
# Turn 1 — no contextId yet
resp1 = await client.send_message(message=msg1)
context_id = resp1.result.contextId   # capture from response

# Turn 2 — use contextId, do NOT reuse the completed taskId
resp2 = await client.send_message(
    message=msg2,
    contextId=context_id,             # continuation key
    # taskId omitted — server assigns a fresh one
)
```

## When taskId IS safe to reuse

If the previous task ended in the `input-required` state (not `completed`),
the task is still active and the client must supply both the original `taskId`
**and** `contextId` to resume that specific task. Only terminal states
(`completed`, `failed`, `canceled`) prohibit taskId reuse.

## Impact

Multi-turn acceptance drivers or harness conversation loops that copy
`taskId` from the previous turn will receive `-32004`/501 on every turn after
the first, causing the entire conversation to fail.
