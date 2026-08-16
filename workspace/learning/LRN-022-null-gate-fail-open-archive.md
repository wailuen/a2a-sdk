---
id: LRN-022
title: Null gate response silently permits archive (fail-open)
category: testing
severity: critical
source: redteam
date: 2026-06-15
---

## What happened
In `template/.claude/workflows/wave-cycle.js` line 1015, the pre-archive gate check uses `if (preArchiveGate && preArchiveGate.exitCode !== 0)`. When the gate agent crashes and returns null, the `&&` short-circuit evaluates to false, skipping the block entirely and allowing archive to proceed with unknown test state. The template also lacks `testsBlockedArchive` tracking, so there is no record that tests were never actually confirmed passing.

## Root cause
A single boolean expression conflates two distinct failure modes — null response (agent crash) and non-zero exit (tests failed) — causing null to be treated as success rather than unknown/blocked.

## Check
```
grep -nE 'if \(preArchiveGate &&' harness/workflows/wave-cycle.js
```
Must not exist; expect separate null-guard (`if (!preArchiveGate)`) and exit-code
(`else if (preArchiveGate.exitCode !== 0)`) branches with `testsBlockedArchive`.

RT-014: the unanchored pattern `grep -n "preArchiveGate &&"` also matches benign
uses of the same identifier, e.g. line 1977's `(preArchiveGate && preArchiveGate.failCount
!= null) ? … : '?'` message-formatting ternary, which is not a gate decision. That
false hit makes a genuine regression indistinguishable from noise. The anchored
`if \(preArchiveGate &&` form above matches only a conditional guard, which is the
actual defect shape this check targets — verify any repointed Check against landed
code before closing a wave, not just against the pattern's plausibility.

```
test -d template/ && diff harness/workflows/wave-cycle.js template/.claude/workflows/wave-cycle.js || echo 'peer repo not checked out — propagation UNVERIFIED'
```
Must print nothing when `template/` is checked out and the copies match. Any diff
output, or the `UNVERIFIED` line, is a failing result — never read silence-by-absence
as a pass.

RT-014/RT-009: the grep above only checks the in-repo propagation source
(`harness/workflows/wave-cycle.js`), not the peer-repo runtime copy
`template/.claude/workflows/wave-cycle.js` (LRN-071). `test_workflow_sync.py`'s
harness↔template axis does not use `skipif` (RT-015/LRN-066): its two presence
guards (`test_acceptance_api_is_harness_template_shared`,
`test_wave_cycle_is_harness_template_shared`) are `@pytest.mark.xfail(not
TEMPLATE_DIR.exists(), strict=True)` — the assertion still runs and still fails
when `template/` is absent, so that state stays visible in the run summary
instead of being silenced (and would XPASS-fail loudly if ever satisfied without
the peer repo). The separate byte-identity axis
(`test_harness_and_template_copies_are_identical`) is not gated at all; it is
parametrized over `HARNESS_TEMPLATE_SHARED`, which is legitimately empty when
`template/` is absent, so pytest reports it as "empty parameter set" — zero test
cases collected, not a pass and not a skip decision. Either way, in a checkout
without the peer repo this axis contributes zero drift coverage for
`wave-cycle.js` — it cannot be cited as the reason peer-copy drift would be
caught. The `diff`/`UNVERIFIED` command above is the actual enforcement for that
copy: it fails loudly on drift when `template/` is present, and reports
`UNVERIFIED` rather than passing silently when it is absent.

## Prevention
Every gate check must use two separate branches: null → fail closed (set testsRed=true, protocolBlocked=true, testsBlockedArchive=true, skip archive); non-zero exitCode → same flags. Never combine null and failure checks with `&&`.
