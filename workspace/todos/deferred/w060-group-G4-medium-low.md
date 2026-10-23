# w060 — unit:G4 deferred medium/low findings

- Wave: w060
- Scope: unit:G4
- Date: 2026-10-23

Non-blocking — these did not block w060's archive. Address opportunistically or fold into a future wave.

## RT-007 (medium) — harness/workflows/wave-cycle.js:1487 [sdkCandidate]

Quote: `hits = [h for h in json.loads(r.stdout or "[]") if norm(h.get("title")) == norm(title)]`

[SDK] Dedupe only catches an open issue whose title exactly equals the new title, and the title is a classifier-rewritten description that changes every run. A re-run of `/wave <id>` (resumption is normal) or an issue already filed by hand with /sdk-issue-scan will not match, so the same bug is filed again. The raw title is also sent as GitHub search text, so qualifiers inside it (`is:`, `label:`, `repo:`) change the search.

Fix: Put a stable fingerprint in the issue body and title, for example `[sdk-fp:<sha1 of component+file+finding id+quote>[:8]]` (the hash only, never the quote). Search for that fingerprint with `--search "<fp> in:body"`, and also search closed issues so a bug fixed upstream is not refiled. Strip `:` qualifiers from free-text search terms. Mirror in sdk-wave.js:1482.

Codify: Dedupe for automated issue filing must key on a stable fingerprint, not on model-written text that changes every run.

## RT-008 (medium) — harness/workflows/wave-cycle.js:1586 [sdkCandidate]

Quote: `if (x.status === 'skipped-secret') log('autoFileSdkIssues: candidate ' + (x.index + 1) + ' still matches a secret pattern after redaction — left for manual /sdk-issue-scan')`

[SDK] Results with status `failed` or `capped`, and candidates the script never reached after a mid-loop `gh issue list` failure, produce no log line and no `Issue:` line. The wave reports success with no sign that filing failed (see RT-001, where every create fails), and sdk-candidates.md does not say which still-open items were attempted. Same in sdk-wave.js:1581.

Fix: Log a count summary (filed/duplicate/failed/capped/skipped-secret/not-attempted) and a per-candidate warning for `failed` and `capped`. Write a `- Filing: failed | capped | not attempted` line into sdk-candidates.md so /sdk-issue-scan knows what is left. Add a behaviour test for a `failed` result.

## RT-009 (low) — harness/workflows/wave-cycle.js:2100 [sdkCandidate]

Quote: `'If this repo is the a2a-sdk repo itself (it has an agent_sdk/ package), EXCLUDE findings\n' +`

[SDK] The AC says SDK-repo process findings (CHANGELOG, todo scope, template-mirror hygiene) are excluded. This is only a prompt instruction to the classifier, which must check for agent_sdk/ by itself. Nothing in the runner enforces it, and check_classifier_keeps_id_and_quote only asserts that the prompt contains the text. Same in sdk-wave.js:2082, where the repo is always the SDK repo, so the condition is redundant there.

Fix: Decide in the runner whether this is the SDK repo (sdk-wave.js always is; for wave-cycle.js read it from wave preflight). Then filter candidates whose file is CHANGELOG.md, under workspace/todos/, or under template/ before filing, or state that the exclusion is advisory.

## RT-010 (low) — tests/test_wave_cycle_behaviour.py:1309 [sdkCandidate]

Quote: `@pytest.mark.parametrize("filed", [None, {"ok": True, "ghAvailable": False, "results": []}, {"ok": False, "ghAvailable": False, "results": []}])`

[SDK] A `@pytest.mark.parametrize` decorator sits on the helper `check_auto_falls_back_to_file`, which is not a test (pytest does not collect `check_*`). The decorator does nothing and repeats the real parametrization at line 1368. Separately, the template mirror commit 2ccf3ac named in the GH-223 CHANGELOG entry was pushed only to origin/feat/gh210-acceptance-turn-helper, not to the template's main branch, so agent repos pulling template main do not get the skill and workflow changes yet.

Fix: Remove the decorator at line 1309. In the CHANGELOG entry, name the template branch (or merge it to template main before release) so 'pushed to wailuen/a2a-agent-template' is accurate.
