---
id: LRN-112
title: Monotonic clock value fed to datetime.fromtimestamp() as if it were epoch time
category: protocol
severity: high
source: redteam
date: 2026-07-11
---

## What happened
AG-UI's `Interrupt.expiresAt` was serialized in `ag_ui.py` via
`datetime.fromtimestamp(event.expires_at, tz=utc)`, where `event.expires_at`
originated from `memory.py`'s `interrupt_deadline = self._clock() + ttl`,
and `_clock` defaults to `time.monotonic()`. Feeding a monotonic reading
(~642000) to `fromtimestamp` produces a garbage ~1970 date instead of the
real wall-clock expiry, so a spec-strict consumer sees the interrupt as
already expired. This was fixed in the same 0.5.40 wave that introduced
this learning (AGUI-1): the internal field was changed to hold a
*relative* seconds-remaining value (`TaskStore.interrupt_ttl_remaining()`)
and `ag_ui.py` now rebases it against wall-clock `time.time()` before
serializing through the shared `iso_utc()` helper — never `fromtimestamp()`
on the raw internal value.

## Update (2026-07-14)
w032/RT-003 renamed the internal field `InterruptEvent.expires_at` →
`expires_in` (it always held a relative duration, and the old name invited
exactly the epoch-vs-duration confusion this learning is about — see
CHANGELOG 0.5.41). That rename was swept through code and CHANGELOG but not
through this file: the Check below still grepped the pre-rename symbol
`event.expires_at`, which no longer appears anywhere in
`agent_sdk/routes/ag_ui.py`, so the grep matched nothing and the guard was
passing "green" for the wrong reason (LRN-079's fail-open-Check pattern)
rather than actually confirming the wall-clock rebase is still in place.
The narrative and Check below are rewritten to the current `expires_in`
idiom.

## Root cause
The internal deadline is computed on a monotonic clock (correct for
in-process timeout comparisons) but must be rebased to wall-clock time
before it crosses the wire-serialization boundary. The landed fix also
makes the internal field itself a clock-agnostic relative duration
(`expires_in`, seconds-remaining) rather than an absolute deadline, so the
rebase happens exactly once, at the wire boundary in `ag_ui.py`:
`wall_deadline = time.time() + event.expires_in`, then
`iso_utc(wall_deadline)`.

## Check
Primary tripwire — behavioral, survives future idiom/rename changes:
```
grep -n 'now.timestamp() < parsed.timestamp() < now.timestamp() + 3600' tests/test_ag_ui.py
```
Must match inside both `test_interrupt_outcome_and_resume` and
`test_interrupt_expiry_is_clock_agnostic` (`tests/test_ag_ui.py`) — these
assert the serialized `expiresAt` parses to a timestamp within the TTL
window of real wall-clock "now", which is impossible if a raw monotonic
reading (or any un-rebased internal deadline) leaks onto the wire.

Secondary — confirms the current rebase idiom is still present:
```
grep -n 'time.time() + event.expires_in' agent_sdk/routes/ag_ui.py
```
Must match. If this grep starts failing, do not assume the bug is fixed
elsewhere first — check whether `expires_in` was renamed or the rebase was
moved/refactored, then update this file's Check accordingly (per LRN-079).

## Prevention
When planning any field that crosses a wire boundary from an internal
deadline/TTL computed via `time.monotonic()`, require an explicit
wall-clock rebase step before serialization, and require a unit test that
asserts the serialized timestamp is within a sane delta of "now" — never
assume a numeric "seconds" value is epoch time without checking its source
clock. Prefer naming the internal field for what it *is* (`expires_in`, a
duration) rather than what it will become after rebasing (`expires_at`, an
instant) — the earlier name was itself a contributor to this confusion.

A field/symbol rename must sweep `workspace/learning/` for the old name —
an LRN `## Check` clause that greps a renamed symbol silently becomes a
dead, fail-open guard (LRN-079) even though the underlying behavior it was
meant to protect is still correct. When renaming a field that any LRN's
Check clause references, grep `workspace/learning/*.md` for the old name as
part of the same rename, same as is already done for code and CHANGELOG.
