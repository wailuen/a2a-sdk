# w064 — Deferred medium/low findings (unit:G6)

- Wave: w064
- Scope: unit:G6
- Date: 2026-10-24

Non-blocking — these did not block w064's archive. Address opportunistically or fold into a future wave.

## RT-001 (medium) — harness/workflows/acceptance-api.js:236
Quote: `if (normalizedArgs.transports != null && !Array.isArray(normalizedArgs.transports)) badArgs.push('transports (must be an array)')`

The new transports guard checks only that the value is an array, not what is in it. A probe with transports ["A2A"], ["ag-ui"] or [5] passes the guard with ranA2A=false and ranAGUI=false. The scenario prompt then has neither the PART 1 nor the PART 2 section, and buildScenarioPrompt's `transports[0].toUpperCase()` throws a TypeError for [5]. A crashed scenario is reified as a2aMinScore 10 and aguiMinScore 10, the 'not tested' score, so the gate can report full marks with no transport exercised. This is the same crash and fail-open class GH-242 set out to close, and the same guard exists in the template mirror line 236.

Fix: In the C-069 block of both copies, add `else if (normalizedArgs.transports != null && normalizedArgs.transports.some(function(t) { return t !== 'a2a' && t !== 'agui' })) badArgs.push('transports (allowed: a2a, agui)')`. Use a fixed message that never echoes the entries. Add a node mutation case to tests/test_gh131_acceptance_api_args_normalization.py for ["A2A"], [5] and ["a2a","x"] that expects an error naming only the field. Commit and push the template copy, staging only .claude/workflows/acceptance-api.js.

Codify: A workflow arg guard must check the allowed values of array entries, not just Array.isArray. An array of unknown values falls through to defaults that score 'not run' as 10/10.

SDK candidate: yes

## RT-002 (low) — harness/workflows/acceptance-api.js:237
Quote: `if (normalizedArgs.onlyIds != null && !Array.isArray(normalizedArgs.onlyIds)) badArgs.push('onlyIds (must be an array)')`

Since GH-242, onlyIds uses exact matching. But a non-empty onlyIds whose entries match no scenario id (a typo, a case slip like "s-1", or a number like 1) still gives scenarios.length 0. The script logs '0/0 scenarios (empty run)' and returns []. The acceptance skill's Phase 2 step 5, 'If all pass → done', then passes an empty result set without any check.

Fix: After the scenarios filter, throw a fixed-message Error when onlyIds is non-empty and the filtered count is 0, for example 'acceptance-api: onlyIds matched no scenario'. Better still, report how many onlyIds entries matched nothing, as a count only. Never echo the ids or the keyFile path. Make the same change in the template mirror and add a node mutation test (onlyIds ["s-1"] → error).

SDK candidate: yes

## RT-003 (low) — tests/test_gh131_acceptance_api_args_normalization.py:120
Quote: `    res = _run_guard(path, _args(onlyIds=["S-1"]))`

test_only_ids_whole_id_match is presented as covering whole-id matching, but it passes on the code from before GH-242 too. Array.prototype.indexOf on an array was already an exact match, and the substring bug only happened when onlyIds was a string. Only test_string_only_ids_does_not_substring_match would fail if the fix were reverted, and it checks only that an 'error' key is present. It does not check that the error names onlyIds or leaves out the keyFile path.

Fix: Relabel test_only_ids_whole_id_match as a regression check that valid input still works, or remove it. Strengthen test_string_only_ids_does_not_substring_match: assert 'onlyIds' in res['error'], assert '/secret/keyfile-path' not in res['error'], and assert 'ids' not in res, so the test fails if the string is ever matched by substring instead of rejected.

SDK candidate: yes
