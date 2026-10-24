# w062 — unit:G4 deferred medium/low findings

- Wave: w062
- Scope: unit:G4
- Date: 2026-10-23

Non-blocking — these did not block w062's archive. Address opportunistically or fold into a future wave.

## RT-001[SDK] (medium) — tests/test_gh131_acceptance_api_args_normalization.py:66

Quote: `assert not re.search(r"\b(rawArgs|args|baseUrl|keyFile|BASE_URL|KEY_FILE)\b(?!['\"])", re.sub(r"'[^']*'", "", body)), body`

The SI-2 no-echo test misses the two most likely leaks. Adding `+ e.message` to the bad-JSON error, or `+ JSON.stringify(normalizedArgs)` to the missing-field error, both pass the test. `\bargs\b` is case-sensitive so it never matches `normalizedArgs`, and `e` / `e.message` is not checked. The JSON.parse SyntaxError text can quote raw input, which includes the admin key path (keyFile). Landed code is clean; the guard would not stop a regression.

Fix: strip string literals, then fail on any remaining name other than `badArgs`, `join` and `+`. At minimum ban `normalizedArgs`, `JSON.stringify`, `e.message`, `\be\b` and template literals. Add a mutation-style test injecting `+ e.message` and `+ JSON.stringify(normalizedArgs)` into a copy of the guard and asserting the checker rejects both.

Codify: a static "error text never echoes the input" test must ban the parsed-object variable and the caught exception's message, not just the raw input name; verify by mutating a copy and confirming the test fails.

sdkCandidate: true

## RT-002[SDK] (medium) — tests/test_gh131_acceptance_api_args_normalization.py:48

Quote: `guard_end = code.index("const BASE_URL")`

test_no_bare_args_read_after_guard only scans from `const BASE_URL` to end of file. About 190 lines of helpers above the guard (lines ~20-211, e.g. buildScenarioPrompt) run after it. A bare `args.x` read in one of them would reintroduce GH-229 (JSON-string args reads as undefined) and the test would pass.

Fix: scan the whole file except the guard block (everything before `let normalizedArgs` plus everything after `const BASE_URL`), asserting no bare `\bargs\b` outside comments. Or assert `args` appears only inside the guard block.

Codify: a "no raw read after normalization" static test must also cover function bodies defined above the guard, since they run after it.

sdkCandidate: true

## RT-003[SDK] (low) — tests/test_gh131_acceptance_api_args_normalization.py:23

Quote: `def _after_guard(text: str) -> str:`

Dead helper, never called. Its marker `const missingArgs` exists in wave-cycle.js, not acceptance-api.js, so it would silently fall back to index 0.

Fix: delete `_after_guard`, or reuse it in RT-002's fix with markers `let normalizedArgs` / `const BASE_URL`.

sdkCandidate: true

## RT-004[SDK] (low) — workspace/todos/active/w062-gh-issues.md:162

The GH-229 Creates: line names `tests/test_gh131_wave_cycle_args_normalization.py`, which is unchanged. Tests landed in new untracked `tests/test_gh131_acceptance_api_args_normalization.py`. CHANGELOG cites the new file; the todo does not, so archive-gate file checks and traceability are wrong.

Fix: update the GH-229 Creates: entry to the new file (drop the wave-cycle path), or move the tests into the named file. Ensure the new test file is staged with the wave commit.

sdkCandidate: true

## RT-005[SDK] (low) — harness/workflows/acceptance-api.js:244

Quote: `const transports = (normalizedArgs.transports && normalizedArgs.transports.length > 0) ? normalizedArgs.transports : ['a2a', 'agui']`

Guard checks scenarios, baseUrl, keyFile but not optional `transports` / `onlyIds` types. String `transports` (e.g. "a2a") passes the length check then crashes with a generic TypeError at `transports.join`. String `onlyIds` (e.g. "S-10") makes the line-247 filter use String.indexOf, a substring match, so "S-1" also re-runs. The line-230 message 'args is not valid JSON object' is misleading when a non-string (array, number) is passed. Same fix applies to template/.claude/workflows/acceptance-api.js, which must stay byte-identical.

Fix: add `if (normalizedArgs.transports != null && !Array.isArray(normalizedArgs.transports)) badArgs.push('transports (must be an array)')` and the same for `onlyIds`. Reword line-230 error to 'args must be an object'. Re-sync the template mirror.

sdkCandidate: true
