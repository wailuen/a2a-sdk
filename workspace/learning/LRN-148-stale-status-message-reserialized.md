---
id: LRN-148
title: Non-user-facing status frame re-serializes stale status.message
category: protocol
severity: high
source: redteam
date: 2026-09-02
---

## What happened
The `AuditEvent` branch publishes `_status_frame(record, metadata=...)`, which
re-serializes `record.task.status` unchanged since `_set_status` is never called for an
audit event. If a prior TextEvent/ProgressEvent set `status.message`, the audit frame
re-emits that same chat sentence a second time on the A2A stream — duplicating agent text
the client renders, and contradicting AuditEvent's own docstring that it never touches
`status.message`.

## Root cause
The audit path reused the general `_status_frame` helper (full status re-serialization)
instead of building a message-free status frame for a non-user-facing event.

## Check
`grep -n "_status_frame(record" agent_sdk/agent/runner.py` at the AuditEvent branch
(~line 763) — confirm the frame is built with `status.message=None`, not the record's
live status. Extend `test_rt009_substitution_audit_not_user_facing.py` to script a text
segment before the substituting tool call and assert `status.message is None` on the
audit frame.

## Prevention
When planning a status-update frame for an event explicitly marked non-user-facing
(audit, internal telemetry), require it to be built with an empty/None `status.message`
by construction, never by re-serializing the record's current (possibly stale) status.
