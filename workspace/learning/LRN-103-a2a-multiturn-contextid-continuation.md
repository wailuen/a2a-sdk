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
error `-32001` (TaskNotFound / task already completed). The server rejects the
message because a task in a terminal state cannot receive further input.

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
`taskId` from the previous turn will receive `-32001` on every turn after the
first, causing the entire conversation to fail.
