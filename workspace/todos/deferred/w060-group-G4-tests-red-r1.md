# w060 — group G4 — tests RED (round 1)

- Wave: w060
- Scope: unit:G4
- Date: 2026-10-23
- Round: 1
- Reason: test suite RED after the fix attempt; blocking findings below remain unresolved.

## Unresolved blocking findings

| ID | Severity | File:line | Summary |
|----|----------|-----------|---------|
| RT-001 | high | harness/workflows/wave-cycle.js:1499 | `gh issue create --label auto-filed` (+ component labels) fails: labels do not exist on wailuen/a2a-sdk; every candidate ends `failed`, not logged. |
| RT-002 | high | .claude/workflows/sdk-wave.js:1494 | Same missing-label defect in sdk-wave.js FILE_SDK_ISSUES_PY. |
| RT-003 | high | harness/workflows/wave-cycle.js:1448 | Redaction `LONG = [A-Za-z0-9+_-]{40,}={0,2}` misses AWS secret (has `/`), Google `AIza` (39 chars), Basic auth, JWT `eyJ`, `glpat-`, `pk_live_`, `password=`, `xoxb-`. |
| RT-004 | high | .claude/workflows/sdk-wave.js:1443 | Same redaction gap in sdk-wave.js. |
| RT-005 | high | harness/workflows/wave-cycle.js:1542 | `originalFinding` joins on id(+file) only, with id-only fallback; repeated RT-NNN ids let a still-open candidate be marked `fixed-in-wave` (fails open). |
| RT-006 | high | .claude/workflows/sdk-wave.js:1537 | Same id-collision defect in sdk-wave.js. |

## Required fixes

- RT-001/002: ensure labels exist (`gh label create <label> -R wailuen/a2a-sdk --force` once per run for `auto-filed` and each COMPONENTS label), or fall back to filing without labels on create failure; log `failed` outcomes. Add fake-gh test where an unknown label makes create exit non-zero and assert it is logged.
- RT-003/004: add `/` and `.` to LONG; lower floor to ~32; add named patterns `AIza[0-9A-Za-z_-]{35}`, `eyJ[A-Za-z0-9_-]+`, `Basic\s+[A-Za-z0-9+/=]+`, `glpat-`, `(?:pk|rk)_(?:live|test)_`, `(?:password|secret|token|api[_-]?key)\s*[=:]\s*\S+`; use them in `leaks()` too. Add each sample to parametrized `test_filer_never_puts_secrets_in_gh_argv_or_body`.
- RT-005/006: match on id AND file AND quote exactly; no match or multiple matches => `still-open`, skip stale check; remove id-only fallback. Add behaviour test with two `RT-001` findings in one file (one fixed, one open) asserting the open one stays `still-open`.
- Keep wave-cycle.js and sdk-wave.js scripts identical (`test_candidate_logic_matches_across_runners`).

## Codify

- Automated `gh issue create --label X` needs X to exist on the target repo; check/create labels first.
- Redaction filters for public output must be tested against real secret formats (AWS, Google, JWT, Basic, GitLab, Stripe).
- Redteam IDs are unique only within one review call; join across rounds by id+file+quote and fail closed on ambiguity.

All six findings are sdkCandidate: true.

## Instruction

Fix failing tests and remaining findings, then re-run `/wave w060`.

Shared working tree rule: never run `git stash`, `git reset`, `git checkout -- <path>`, `git restore`, `git clean`, or `git checkout .`. Edit files in place; use `git show` / `git diff` to inspect old content.
