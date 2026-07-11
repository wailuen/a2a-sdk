---
id: LRN-112
title: Monotonic clock value fed to datetime.fromtimestamp() as if it were epoch time
category: protocol
severity: high
source: redteam
date: 2026-07-11
---

## What happened
AG-UI's `Interrupt.expiresAt` is serialized in `ag_ui.py:313` via
`datetime.fromtimestamp(event.expires_at, tz=utc)`, but `event.expires_at`
originates from `memory.py`'s `interrupt_deadline = self._clock() + ttl`,
where `_clock` defaults to `time.monotonic()` and is never overridden at
`app.py:507`. Feeding a monotonic reading (~642000) to `fromtimestamp`
produces a garbage ~1970 date instead of the real wall-clock expiry, so a
spec-strict consumer sees the interrupt as already expired.

## Root cause
The internal deadline is computed on a monotonic clock (correct for
in-process timeout comparisons) but crossed the wire-serialization boundary
without being rebased to wall-clock time first.

## Check
```
grep -n 'fromtimestamp(event.expires_at' agent_sdk/routes/ag_ui.py
```
Must NOT show a bare `event.expires_at` passed directly — confirm a
wall-clock rebase (`time.time() + (event.expires_at - time.monotonic())`)
precedes any `fromtimestamp()`/`iso_utc()` call. Add/require a test
asserting the serialized `expiresAt` year matches `datetime.now(UTC).year`,
not 1970.

## Prevention
When planning any field that crosses a wire boundary from an internal
deadline/TTL computed via `time.monotonic()`, require an explicit
wall-clock rebase step before serialization, and require a unit test that
asserts the serialized timestamp is within a sane delta of "now" — never
assume a numeric "seconds" value is epoch time without checking its source
clock.
