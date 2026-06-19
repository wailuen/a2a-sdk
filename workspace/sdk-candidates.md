# SDK issue candidates — w021 ((see context date))

Run `/sdk-issue-scan` to review and file as GitHub issues on `wailuen/a2a-sdk`.

## Candidate 1: Store-sourced Bedrock bearer token written into os.environ["AWS_BEARER_TOKEN_BEDROCK"] — a process-global credential mutation that persists for the process lifetime and is inherited by any subprocess, re-introducing the SI-6 env-leak risk the credential store was meant to eliminate.
- Severity: high
- Component: sdk/credentials
- File: agent_sdk/agent/bedrock.py:50
- Rationale: This is an SDK-internal credential handling violation in the Bedrock client — not agent-domain tool code. The credential store and its invariants (SI-6: upstream vendor keys must never land in env) are SDK responsibilities. The fix (scope the token to the boto3 session/config, not os.environ) belongs entirely in the SDK's bedrock.py client.

## Candidate 2: Acceptance A2A probe reads only part["metadata"]["mimeType"] for content-type extraction, but the SDK runner emits {data_type, tool_name} (no mimeType) for ContentModel DataParts when X-A2A-Extensions is absent, causing contentTypes=[] for every A2A artifact and systematically under-scoring A2A transport.
- Severity: high
- Component: harness/workflow
- File: harness/workflows/acceptance-api.js:138-141
- Rationale: The probe logic lives in harness/workflows/acceptance-api.js and is an SDK harness workflow concern — it defines how acceptance scoring works across transports. The SDK runner's ContentModel DataPart metadata contract (runner.py:171) is also SDK-internal. Neither is agent-domain code.

## Candidate 3: template/.claude/workflows/acceptance-api.js is a stale fork retaining all GH-71 bugs: slash path /v1/message/stream, JSON-RPC envelope wrapper, missing messageId, stale taskStatusUpdated/taskArtifactUpdated event parsing, bare thread-ID paths, missing followUpTurns handling, and missing harness-contamination enum value.
- Severity: high
- Component: harness/template
- File: template/.claude/workflows/acceptance-api.js
- Rationale: This is explicitly a template scaffold sync gap — the harness/workflows/ fix was not propagated to the template peer repo. New agents scaffolded from template ship the broken acceptance runner. The template scaffold is a defined SDK component boundary.

## Candidate 4: harness/skills/acceptance/SKILL.md still documents the pre-fix wire protocol: POST /v1/message/stream (slash) with JSON-RPC envelope, POST /ag-ui/run, deterministic threadId, missing messageId, and stale SSE event shape (method/params) — re-documenting the four GH-71 bugs the workflow fix corrected and the LRN-040 concurrent-run contamination.
- Severity: high
- Component: harness/skill
- File: harness/skills/acceptance/SKILL.md:144-211
- Rationale: SKILL.md is the canonical caller specification for the acceptance skill — it is an SDK harness/skill artifact. Drift between SKILL.md and the corrected acceptance-api.js workflow is an SDK-level runtime/spec gap, not agent-domain.

## Candidate 5: bedrock.py calls botocore.tokens.ScopedEnvTokenProvider / TokenProviderChain, added in botocore 1.39 (boto3 1.39.0), but pyproject.toml pins only boto3>=1.34. Any consumer on the permitted 1.34-1.38 floor crashes with AttributeError at first Bedrock bearer-token call. The 18 GH-72 tests are masked by monkeypatching; uv.lock carries 1.43 masking the bug from CI.
- Severity: critical
- Component: sdk/build
- File: agent_sdk/agent/bedrock.py:60-79
- Rationale: This is an SDK dependency floor and build/packaging correctness issue — pyproject.toml is an SDK build artifact, and bedrock.py is SDK internals. The gap between the declared lower bound and the code's runtime requirements is a pure SDK/build concern, not agent-domain.

## Candidate 6: acceptance-api.js silently drops null scenario results via .filter(Boolean), removing crashed/timed-out scenarios from the denominator and reporting e.g. '3/3 passed' when 2 of 5 crashed — a false-pass against the 100% acceptance gate. With all-null results the reduce returns its initial value over zero scenarios.
- Severity: high
- Component: harness/workflow
- File: harness/workflows/acceptance-api.js:282
- Rationale: The null-result drop is in the SDK harness workflow orchestrator (acceptance-api.js). The fail-open scoring anti-pattern (LRN-019/020/030/063) is an SDK harness invariant. wave-cycle.js already guards against this pattern; acceptance-api.js must match. No agent-domain logic is involved.

## Candidate 7: LRN-073 ## Check clause greps .claude/workflows/acceptance-api.js, a path that does not exist in this repo — acceptance-api.js has no .claude/workflows/ copy and lives only at harness/workflows/ and template/.claude/workflows/. The grep silently passes on a missing file, making the codified guard a dead no-op.
- Severity: high
- Component: harness/skill
- File: workspace/learning/LRN-073-acceptance-filter-boolean-nan-denominator.md
- Rationale: The learning file is owned by the /codify skill (harness/skills/codify/) and its Check clause is the mechanism by which the redteam loop enforces the learning. A wrong file path in ## Check is an SDK harness/skill authoring defect, not agent-domain code.

## Candidate 8: LRN-073 ## Fix code block documents failureClass: 'harness-contamination' for null agent results, but the landed acceptance-api.js:299 uses failureClass: 'code-bug'. The w021 deferred ledger explicitly states harness-contamination is wrong for null results. The learning teaches the wrong enum value (LRN-066 anti-pattern).
- Severity: high
- Component: harness/skill
- File: workspace/learning/LRN-073-acceptance-filter-boolean-nan-denominator.md
- Rationale: Same as above — the learning file is a /codify skill artifact. The mismatch between the LRN ## Fix snippet and the landed code is an SDK harness/skill documentation integrity issue (LRN-066 class), not agent-domain.
