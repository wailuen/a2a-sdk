# SDK issue candidates — w060 (2026-10-23)

Run `/sdk-issue-scan` to review and file as GitHub issues on `wailuen/a2a-sdk`.

## Candidate 1: RT-001 (line 64): The 'ID A or ID B' recipe puts anyOf at the top level of a tool's input schema via model_config json_schema_extra. The schema goes unchanged to the model (loop.py -> bedrock.py inputSchema.json / openai_client.py parameters) and to MCP clients via tools/list. Anthropic rejects top-level oneOf/allOf/anyOf in input_schema with a 400, so following the doc breaks every Claude-on-Bedrock turn and Claude MCP connector tool lists. tests/test_gh221_tools_list_titles.py::test_any_of_required_reaches_tools_list pins the unsafe shape. Fix: warn against top-level combinators, recommend optional fields + in-tool/model_validator check; optionally have C-056 _check_list and boot validation flag top-level combinators in tier-1 inputSchema.
- Severity: high
- Component: sdk/loop
- File: docs/tools.md
- Rationale: SDK documentation for tool input schemas plus SDK loop/provider adapters and MCP tools/list behaviour; affects every agent built on the SDK, not one agent's domain code.

## Candidate 2: RT-001 (line 1499): FILE_SDK_ISSUES_PY always runs `gh issue create ... --label auto-filed --label <component>`, but those labels do not exist on wailuen/a2a-sdk, so gh refuses every create, every candidate ends `failed`, nothing is filed, and fileStillOpenCandidates does not log the failure. Fake-gh tests accept any label. Fix: create/check labels first (gh label create --force) or fall back to no labels; add a fake-gh test where an unknown label makes create fail.
- Severity: high
- Component: harness/workflow
- File: harness/workflows/wave-cycle.js
- Rationale: Defect in the shared harness wave workflow script that ships to agent repos via the template.

## Candidate 3: RT-002 (line 1494): Same missing-label defect in the sdk-wave.js copy of FILE_SDK_ISSUES_PY; with autoFileSdkIssues=true every gh issue create fails and nothing is filed. Fix identically to wave-cycle.js and keep the scripts identical (test_candidate_logic_matches_across_runners).
- Severity: high
- Component: harness/workflow
- File: .claude/workflows/sdk-wave.js
- Rationale: Defect in the SDK-repo wave runner workflow script (harness tooling).

## Candidate 4: RT-003 (line 1448): Redaction before public GitHub issue filing misses common secrets: LONG regex `[A-Za-z0-9+_-]{40,}` excludes '/' (standard base64, e.g. AWS secret keys) and '.', and the 40-char floor misses 39-char Google AIza keys; Basic auth, JWT headers (eyJ...), glpat-, pk_live_, password=..., xoxb- all pass with leaks()=False. Fix: add '/' and '.' to the class, lower floor to ~32, add named patterns (AIza, eyJ, Basic, glpat-, pk|rk_live|test_, password/secret/token/api_key=...), use them in leaks(), extend test_filer_never_puts_secrets_in_gh_argv_or_body, mirror in sdk-wave.js.
- Severity: high
- Component: security
- File: harness/workflows/wave-cycle.js
- Rationale: Secret-leak path in harness automation that posts to a public repo with no human check; security issue in shared harness code.

## Candidate 5: RT-004 (line 1443): Same redaction gap in the sdk-wave.js filer: base64 with '/', 39-char Google keys, Basic auth, JWT headers, glpat/pk_live tokens and password= values pass redaction and can be posted to a public issue. Apply the same pattern changes as wave-cycle.js and keep runners identical.
- Severity: high
- Component: security
- File: .claude/workflows/sdk-wave.js
- Rationale: Security gap in SDK-repo harness workflow that publishes content to GitHub.

## Candidate 6: RT-005 (line 1542): originalFinding joins candidates to findings by id (+file) with an id-only fallback, but redteam IDs restart at RT-001 every call. A still-open candidate can match an earlier fixed finding with the same id/file and be marked fixed-in-wave, so it is neither filed nor sent to /sdk-issue-scan (fails open). Fix: match on id+file+quote exactly; on zero or multiple matches mark still-open and skip the stale check; drop id-only fallback; add a two-RT-001 behaviour test; mirror in sdk-wave.js.
- Severity: high
- Component: harness/workflow
- File: harness/workflows/wave-cycle.js
- Rationale: Logic defect in shared harness wave workflow candidate tracking.

## Candidate 7: RT-006 (line 1537): Same id-collision defect in sdk-wave.js originalFinding; repeated RT-NNN ids across units/rounds let a still-open SDK candidate be marked fixed-in-wave. Fix: id+file+quote exact match, fail closed to still-open, drop id-only fallback, keep parity with wave-cycle.js.
- Severity: high
- Component: harness/workflow
- File: .claude/workflows/sdk-wave.js
- Rationale: Logic defect in SDK-repo wave runner workflow.
