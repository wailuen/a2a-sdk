# SDK issue candidates — w036 (2026-08-15)

These critical/high findings from wave w036 are classified as
SDK-level. Run `/sdk-issue-scan` to review and file them as GitHub issues
on `wailuen/a2a-sdk`. One confirmation per filing — nothing is filed automatically.

## Candidate 1: GH-135 reroutes tool-body ValidationError into the catch-all `except Exception: logger.exception(...)` in mcp.py:450 and admin.py:568, which logs pydantic's raw message including the rejected input value (SI-2 leak).
- Severity: critical
- Component: security
- File: agent_sdk/routes/mcp.py
- Rationale: SI-2 violation caused directly by SDK protocol-route exception handling, not by any domain code.

## Candidate 2: GH-131 args-normalization and the entire GH-132 severity-floor/budget/LRN-cap fix landed in both wave-cycle.js copies but was never ported to sibling runner sdk-wave.js, which retains the old fail-open findingsCount check and no AGENT_CALL_BUDGET/MAX_LRN_PER_WAVE.
- Severity: critical
- Component: harness/workflow
- File: .claude/workflows/sdk-wave.js
- Rationale: wave-cycle.js logic error / cross-runner drift in the harness's own workflow runner.

## Candidate 3: `ToolInputValidationError.__init__` sets the message to `str(validation_error)`, which pydantic renders with the raw rejected value embedded — the exact SI-2 leak shape GH-135's AC forbade.
- Severity: high
- Component: security
- File: agent_sdk/agent/registry.py
- Rationale: SI-2 violation in the SDK's own exception-wrapping code (registry.py), not domain code.

## Candidate 4: GH-130's row-fabrication delimiter defense only strips CR/LF; U+2028, NEL, VT, FF and C0 controls still fabricate table rows through to the A2A/MCP wire.
- Severity: high
- Component: security
- File: agent_sdk/models/content_types.py
- Rationale: SDK-internal content-rendering sanitizer bypass; SI violation caused by the SDK itself.

## Candidate 5: GH-130's `_sanitize_cell` fix was applied to only 2 of 14 `to_plain_text()` renderers, leaving MessageList, BarChart, KpiGroup, WaterfallChart and others interpolating untrusted fields unsanitized.
- Severity: high
- Component: security
- File: agent_sdk/models/content_types.py
- Rationale: Incomplete security fix across SDK base-class renderers, an SI violation the SDK itself causes.

## Candidate 6: The `Reuses: C-007` annotation required the delimiter-neutralization helper to land in `agent_sdk/common/redact.py`, but `_sanitize_cell` was instead created inside content_types.py, creating a divergent copy of the registered component.
- Severity: high
- Component: sdk/build
- File: agent_sdk/models/content_types.py
- Rationale: SDK-internal code-organization/component-reuse violation inside the SDK package itself.

## Candidate 7: GH-132's severity floor exits the loop on `blocking.length === 0`, but the LRN-028 reconciliation guard only repairs `findingsCount===0 with items`, not `findingsCount>0 with empty findings array` — a new zero-tolerance fail-open.
- Severity: high
- Component: harness/workflow
- File: .claude/workflows/wave-cycle.js
- Rationale: Wave-cycle.js loop-gate logic error in the harness workflow runner.

## Candidate 8: GH-135's SI-2 AC required internal catch-alls to log detail via `logger.exception`, but loop.py's three catch-all branches (lines 500/531/584) bind no exception and log nothing, silently swallowing ValidationErrors on the primary tool-dispatch path.
- Severity: high
- Component: sdk/loop
- File: agent_sdk/agent/loop.py
- Rationale: SDK-internal agent loop exception-handling defect, explicitly in the 'loop' SDK-internals category.

## Candidate 9: GH-133's new `max_retries`/`timeout` kwargs are never wired: `Agent._build_model_client()` constructs `OpenAIModelClient` without them and no settings field/env var exists, so the throttling fix is unreachable.
- Severity: high
- Component: sdk/build
- File: agent_sdk/app.py
- Rationale: Dead configuration in the SDK's own `build_app`/Agent client-construction wiring.

## Candidate 10: The GH-134 CHANGELOG entry (MCP `tools/list` openWorldHint wire-shape flip) was appended into an already-tagged `[0.5.44]` release section and miscategorized as protocol surface instead of a breaking behavior change.
- Severity: high
- Component: protocol/mcp
- File: CHANGELOG.md
- Rationale: Misdocumented MCP wire-visible protocol change in the SDK's own release notes.

## Candidate 11: GH-135's SI-2 AC mandated a named regression test proving a secret-looking ValidationError value never reaches the wire/model on every dispatch surface (loop/MCP/admin/commitments), but the landed test covers only loop.py with non-secret values.
- Severity: high
- Component: security
- File: tests/test_gh135_tool_body_validation_error.py
- Rationale: Test-coverage gap for a security-AC regression test in SDK code, which is why the RT-001 log leak shipped undetected.

## Candidate 12: template/.claude/workflows/wave-cycle.js, a declared deliverable of both GH-131 and GH-132, was never updated — the peer-repo runtime copy downstream agents execute still has the pre-fix bugs.
- Severity: high
- Component: harness/template
- File: .claude/workflows/wave-cycle.js
- Rationale: Wave-cycle.js/template propagation failure — a harness-template deliverable never landed.

## Candidate 13: test_acceptance_api_is_harness_template_shared was converted from a hard assertion into a skipif-when-template-missing, silencing the only signal that harness↔template propagation is unverifiable.
- Severity: high
- Component: harness/workflow
- File: tests/test_workflow_sync.py
- Rationale: Harness test-guard for the workflow-sync mechanism was weakened, hiding drift in the harness itself.

## Candidate 14: PLAN_RT_SCHEMA now requires `peerRepoAnnotations`, but the redteam agent's own instruction file still documents Mode 2 with 5 keys and no `peerRepoAnnotations`, so a compliant agent emits a schema-invalid object and the phase fails open.
- Severity: high
- Component: harness/agent
- File: .claude/workflows/wave-cycle.js
- Rationale: Mismatch between a workflow schema and the harness agent instruction file (.claude/agents/core/redteam.md) that must produce it.

## Candidate 15: The RT-014 peer-repo propagation check was added to wave-cycle.js's schema/prompt but omitted from sdk-wave.js — backwards, since sdk-wave.js is the runner that actually executes in the a2a-sdk repo where the gap occurs.
- Severity: high
- Component: harness/workflow
- File: .claude/workflows/sdk-wave.js
- Rationale: Gate ported to the wrong/incomplete set of harness workflow runners.

## Candidate 16: GH-132 changed the unit/phase redteam loops from zero-findings to severity-floor exit, but every companion SKILL.md still advertises the old 'zero-tolerance' contract with no mention of the severity floor, deferred notes, or budget.
- Severity: high
- Component: harness/skill
- File: .claude/skills/wave/SKILL.md
- Rationale: Harness skill documentation left stale after a workflow gate's contract changed.

## Candidate 17: EntityList.to_plain_text renders `self.entity_type` (a free-form str) with no sanitisation, fabricating rows via embedded newlines; the meta-test only checks that `_sanitize_cell(` appears somewhere in the function, not per-field.
- Severity: high
- Component: security
- File: agent_sdk/models/content_types.py
- Rationale: SDK base-class renderer sanitisation gap plus an inadequate enforcement test, both SDK-internal SI issues.

## Candidate 18: GH-134's MCP wire-shape break and GH-135's dispatch exception-type break are both filed under `### Behavior changes` instead of the mandatory `### Breaking changes` heading DESIGN.md §4.0 requires for the wire-shape exemption.
- Severity: high
- Component: protocol/mcp
- File: CHANGELOG.md
- Rationale: Misfiled protocol-breaking-change documentation for the SDK's stable-core wire surface.

## Candidate 19: LRN-044 (critical, live) asserts every bare `except Exception` must either re-raise ValidationError or enrich the error body with the class name; GH-135 deliberately reverses this and the learning was never superseded or rewritten.
- Severity: high
- Component: harness/workflow
- File: workspace/learning/LRN-044-validationerror-swallowed-in-catch-all.md
- Rationale: Stale learning-registry entry (harness codify system) contradicting landed SDK code.

## Candidate 20: MarketBriefing.prose is appended raw into to_markdown()'s joined lines while every sibling free-form field now routes through _sanitize_cell, reopening the GH-130 row-fabrication attack on the model-facing and MCP structuredContent path.
- Severity: high
- Component: security
- File: agent_sdk/models/content_types.py
- Rationale: Unsanitized untrusted field in an SDK base-class renderer, SI violation caused by the SDK itself.

## Candidate 21: AGENT_CALL_BUDGET is a fixed module constant with no args/env override; a wave whose honest cost exceeds 150 calls aborts deterministically on every retry with a remediation ('re-run /wave') that cannot succeed.
- Severity: high
- Component: harness/workflow
- File: .claude/workflows/wave-cycle.js
- Rationale: Hard-coded cost backstop with no operator override in the harness workflow runner.

## Candidate 22: GH-131/GH-132 declare template/.claude/workflows/wave-cycle.js as a deliverable but tests/test_workflows.py's `_existing_wf_files` helper silently drops the missing path from parametrization, letting the suite pass green while the peer-repo copy is unsynced.
- Severity: high
- Component: harness/template
- File: .claude/workflows/wave-cycle.js
- Rationale: Harness template-sync test helper masks an unlanded peer-repo deliverable.

## Candidate 23: GH-130's `_sanitize_cell` was applied to MarketBriefing.to_markdown(), which is a multi-line markdown wire payload — collapsing newlines and rewriting '|' destroys headings, lists and tables in the SDK's own designated prose type.
- Severity: high
- Component: security
- File: agent_sdk/models/content_types.py
- Rationale: Sanitizer misapplication in SDK core rendering code causing wire-payload corruption, an SDK-internal defect.

## Candidate 24: The RT-009 accumulate-non-blocking fix (medium/low findings capture) landed only in the two wave-cycle.js copies; sdk-wave.js has no accumulateNonBlocking helper and discards medium/low findings on every non-clean exit path.
- Severity: high
- Component: harness/workflow
- File: .claude/workflows/sdk-wave.js
- Rationale: Cross-runner drift in the harness workflow runner's finding-capture logic.

## Candidate 25: agent_sdk/routes/mcp.py, routes/admin.py, __init__.py, and agent_sdk/common/redact.py were modified but appear in no todo's Creates:/Modifies: line, evading every archive-gate scope check.
- Severity: high
- Component: harness/workflow
- File: workspace/todos/active/w036-gh-issues.md
- Rationale: Wave scope-declaration gap in the harness's own todo/archive-gate process.

## Candidate 26: The propagation guards for the missing template/ peer-repo mirror are xfail(strict=True) rather than hard blocks, so an unsynced template deliverable never blocks archive.
- Severity: high
- Component: harness/template
- File: .claude/workflows/wave-cycle.js
- Rationale: Harness archive-gate template-propagation guard silently degrades instead of blocking.

## Candidate 27: template/.claude/workflows/wave-cycle.js is declared in both GH-131 and GH-132's Creates: with explicit git-push instructions, both todos marked [x], but the file was never updated; propagation guards report xfail not pass.
- Severity: high
- Component: harness/template
- File: harness/workflows/wave-cycle.js
- Rationale: Unlanded harness-template peer-repo deliverable marked complete without verification.

## Candidate 28: sdk-wave.js is missing the RT-004 archive hard-block for a missing template/ checkout (templateDirExists schema field, step-0 check, declaresTemplateScope branch) that landed in the wave-cycle.js copies.
- Severity: high
- Component: harness/workflow
- File: .claude/workflows/sdk-wave.js
- Rationale: Archive-gate clause ported to only some harness workflow runners, leaving sdk-wave.js without the guard.

## Candidate 29: The phase redteam round-cap exit (`if (pRound >= 8) break`) writes no deferred note and runs before the codify capture, so surviving critical/high findings at round 8 are never recorded and the wave archives as clean.
- Severity: high
- Component: harness/workflow
- File: .claude/workflows/wave-cycle.js
- Rationale: Fail-open loop-exit path in the harness workflow runner's phase-redteam gate.

## Candidate 30: The unit redteam round-cap exit (`if (uRound >= 5)`) writes a deferred note but sets no blocking flag and breaks before capturing surviving findings for codify, letting the wave proceed to archive.
- Severity: high
- Component: harness/workflow
- File: .claude/workflows/wave-cycle.js
- Rationale: Fail-open loop-exit path in the harness workflow runner's unit-redteam gate.

## Candidate 31: test_lrn_check_grep_paths_exist truncates grep-pattern parsing on any pipe character inside quotes and stops scanning after the first fenced block, so nine LRN Checks referencing the nonexistent template/ path stay undetected.
- Severity: high
- Component: harness/workflow
- File: tests/test_learning_index.py
- Rationale: Parsing bug in the harness's own learning-registry dead-path validation gate.

## Candidate 32: AGENT_CALL_BUDGET defaults to 150, below the wave's own documented honest cost for a routine 4-group wave (~157 calls), so the backstop trips on normal usage.
- Severity: high
- Component: harness/workflow
- File: .claude/workflows/wave-cycle.js
- Rationale: Miscalibrated hard cost backstop in the harness workflow runner.

## Candidate 33: agent_sdk/contrib/commitments/executor.py was modified (new ToolInputValidationError handling) but never added to GH-135's Creates:/Modifies:, evading the archive-gate scope checks.
- Severity: high
- Component: harness/workflow
- File: agent_sdk/contrib/commitments/executor.py
- Rationale: The defect is the harness todo-scope declaration gap, not the code change itself; belongs to the archive-gate process.

## Candidate 34: GH-130's delimiter-safety contract was documented only on the private ContentModel docstring; the public authoring guide docs/content-types.md still shows an unsanitized to_plain_text() example, re-introducing the vulnerability for every downstream author.
- Severity: high
- Component: security
- File: docs/content-types.md
- Rationale: SDK-authored public documentation teaches a vulnerable pattern for the SDK's own extension point.

## Candidate 35: The GH-132 round-cap rework (deferred notes, codify capture ordering, blocking flags) landed in both wave-cycle.js mirrors but not sdk-wave.js, whose phase/unit round-caps still archive with surviving critical/high findings uncaptured.
- Severity: high
- Component: harness/workflow
- File: .claude/workflows/sdk-wave.js
- Rationale: Redteam-loop gate fix not ported to a sibling harness workflow runner.

## Candidate 36: UserList.job_title, UserProfile.job_title/department, and DocumentList's `when` field are sanitized without the angle-bracket/paren confusable maps used by their neighboring delimiter-owning fields, letting an adjacent untrusted field fabricate a second identity pair on the same line.
- Severity: high
- Component: security
- File: agent_sdk/models/content_types.py
- Rationale: Incomplete delimiter-safety contract enforcement in SDK base-class renderers.

## Candidate 37: Four redteam loop-exit paths (null-response and findings-count-mismatch round-budget exits, unit and phase) write a deferred note but set no blocking flag, so an UNKNOWN redteam verdict on every round still lets the wave archive as clean.
- Severity: high
- Component: harness/workflow
- File: .claude/workflows/wave-cycle.js
- Rationale: Fail-open behavior in the harness workflow runner's redteam-verdict handling despite comments claiming fail-closed.

## Candidate 38: Wave ID 'w036' collides with an already-archived wave of the same basename in workspace/todos/completed/, so the archive step's `mv` silently overwrites the earlier wave's record.
- Severity: high
- Component: harness/workflow
- File: workspace/todos/active/w036-gh-issues.md
- Rationale: Wave-ID uniqueness gap in the harness's archive/mv logic, with no Parse-phase guard against collision.

## Candidate 39: template/.claude/workflows/wave-cycle.js, declared by GH-131/GH-132 with explicit git-push instructions, still does not exist; the propagation guards degrade to xfail rather than failing.
- Severity: high
- Component: harness/template
- File: harness/workflows/wave-cycle.js
- Rationale: Recurrence of the unlanded harness-template peer-repo deliverable, still open.

## Candidate 40: Three further w036 fixes (JSON.parse try/catch on args, group-count-scaled AGENT_CALL_BUDGET, MAX_LRN_PER_WAVE deferred-note write) landed only in the wave-cycle.js mirrors, leaving sdk-wave.js with the original defects.
- Severity: high
- Component: harness/workflow
- File: .claude/workflows/sdk-wave.js
- Rationale: Multiple harness gate/robustness fixes not ported to the sdk-wave.js runner.

## Candidate 41: template/.claude/workflows/wave-cycle.js is declared complete (todos marked [x]) but was never landed; the local template clone still carries the pre-fix code and the propagation guards are xfail.
- Severity: high
- Component: harness/template
- File: harness/workflows/wave-cycle.js
- Rationale: Harness deliverable falsely marked complete without verification of the peer-repo state.

## Candidate 42: GH-139's three new actionable bearer-auth RuntimeErrors are unreachable: converse()'s catch-all wraps `_boto_client()` and re-raises a fixed generic AgentError with no logging of the cause, so the actionable messages never reach an operator.
- Severity: high
- Component: sdk/credentials
- File: agent_sdk/agent/bedrock.py
- Rationale: Unreachable credential/auth error messages in the SDK's Bedrock model-client construction path.

## Candidate 43: LRN-104 requires `except ModuleNotFoundError: raise` above any broad catch-all in a model client's invoke path; bedrock.py's converse() and _boto_client() catch-alls lack it, so a missing boto3/botocore install surfaces as an opaque generic error.
- Severity: high
- Component: sdk/build
- File: agent_sdk/agent/bedrock.py
- Rationale: SDK-internal model-client deferred-import handling pattern violated, a codified cross-client invariant.

## Candidate 44: GH-134's Breaking-changes CHANGELOG entry cites DESIGN.md §4.0's `models/` wire-shape exemption for `ToolDecl.annotations`, but ToolDecl is actually defined in agent_sdk/agent/registry.py, not models/ — a false exemption citation.
- Severity: high
- Component: protocol/mcp
- File: CHANGELOG.md
- Rationale: Incorrectly justified protocol wire-shape breaking-change exemption in the SDK's own release documentation.

## Candidate 45: The Parse-phase scope extraction only harvests bare Creates:/Modifies: paths, missing paths named inside parenthetical '(modifies a, b, c)' prose — silently narrowing wave.allScope and disabling every downstream gate keyed off it.
- Severity: high
- Component: harness/workflow
- File: .claude/workflows/wave-cycle.js
- Rationale: Scope-extraction defect in the harness workflow runner's Parse phase.

## Candidate 46: This wave was executed with wave-cycle.js (whose protocol-surface arrays are `src/`-prefixed) instead of sdk-wave.js inside the a2a-sdk repo (source under `agent_sdk/`), so Protocol Audit never ran; SKILL.md's Mode B instruction ambiguously says 'launch wave-cycle.js as in Mode A step 2'.
- Severity: high
- Component: harness/skill
- File: .claude/skills/wave/SKILL.md
- Rationale: Ambiguous harness skill instruction caused the wrong workflow runner to execute, skipping Protocol Audit entirely.

## Candidate 47: The offendingUndeclaredScope check hardcodes `agent_sdk/**.py` inside wave-cycle.js, the downstream-agent runner whose source root is `src/`, making the check a permanent no-op in its actual target repos.
- Severity: high
- Component: harness/workflow
- File: .claude/workflows/wave-cycle.js
- Rationale: Path-dialect mismatch in a harness workflow runner's archive-gate scope check.

## Candidate 48: MultiCategoryChart's comma/equals separators and UserList's em-dash joiner are not covered by any confusable map, so untrusted category keys or display names still fabricate extra category/value pairs or forged job titles.
- Severity: high
- Component: security
- File: agent_sdk/models/content_types.py
- Rationale: Incomplete delimiter-fabrication defense in SDK base-class renderers, an SI violation caused by the SDK.

## Candidate 49: The archive gate's import cross-check resolves absolute imports rooted at `agent_sdk` only, but wave-cycle.js is the downstream-agent runner whose source root is `src/`, making the absolute-import half of the gate a permanent no-op there.
- Severity: high
- Component: harness/workflow
- File: .claude/workflows/wave-cycle.js
- Rationale: Source-root dialect mismatch in a harness workflow runner's import-resolution gate.

## Candidate 50: GH-130's delimiter-safety helpers (`_sanitize_cell`, separator maps) are module-private and unexported, yet the ContentModel docstring, docs/content-types.md and DESIGN.md §4.0 all mandate third-party domain-card authors call/reimplement this exact sanitisation.
- Severity: high
- Component: security
- File: agent_sdk/models/content_types.py
- Rationale: SDK security contract documented but its enforcing helper never exposed as a public SDK API, guaranteeing divergent reimplementation.

## Candidate 51: `(await parallel(advisorTasks)).filter(Boolean)` silently drops crashed/null protocol advisor results, so a crashed advisor contributes 0 findings and the wave archives as protocol-clean without ever having been audited.
- Severity: critical
- Component: harness/workflow
- File: .claude/workflows/wave-cycle.js
- Rationale: Fail-open null-handling bug in the harness workflow runner's Protocol Audit aggregation, the only unguarded parallel() result in the file.

## Candidate 52: LRN-028's Check greps a nonexistent template/ path and a pattern (`findingsCount === 0 && rt.findings.length`) this same wave's RT-016 replaced with a different invariant, so the Check can never fail against landed code.
- Severity: high
- Component: harness/workflow
- File: workspace/learning/LRN-028-redteam-findings-count-mismatch.md
- Rationale: Stale/dead learning-registry Check clause in the harness codify system.

## Candidate 53: The LRN dead-path guard's grep-path extractor doesn't reassemble backslash-continued shell lines, so paths on continuation lines (including the ones in LRN-028/036/037) are never scanned and stay invisible to the guard.
- Severity: high
- Component: harness/workflow
- File: tests/test_learning_index.py
- Rationale: Parsing gap in the harness's own learning-registry dead-path validation test.

## Candidate 54: pyproject.toml was modified mid-wave (weakening `filterwarnings` to suppress unraisable-exception warnings) with no todo declaring it, and is invisible to all four archive-gate scope-check clauses simultaneously.
- Severity: high
- Component: harness/workflow
- File: pyproject.toml
- Rationale: Root-config file sits outside every existing archive-gate scope clause in the harness workflow runner.

## Candidate 55: GH-131/GH-132 remain unchecked with their declared template/ deliverable unlanded, and the wave is now unresumable because the Parse-phase template-dir hard abort (added by this same wave) fires before any phase can run.
- Severity: high
- Component: harness/template
- File: workspace/todos/active/w039-gh-issues.md
- Rationale: Harness template-propagation deliverable left undone, compounded by a self-inflicted resumability deadlock in the workflow runner.

## Candidate 56: The wave-scope extraction rule accepts bare directory and glob tokens from prose, so a mention like `agent_sdk/` in an explanatory parenthetical silently declares the whole tree in-scope, disabling the offendingUndeclaredScope archive gate.
- Severity: high
- Component: harness/workflow
- File: agent_sdk/harness/wave_scope.py
- Rationale: Scope-extraction defect in the harness's own wave-scope module, defeating its own archive-gate check; a passing test actively pins the bug.

## Candidate 57: Several LRN `## Check` clauses were rewritten to drop the template/ grep on the justification that test_workflow_sync.py's harness↔template axis already covers it — false in this checkout, where that axis yields zero parametrized cases and two xfail guards.
- Severity: high
- Component: harness/workflow
- File: workspace/learning/LRN-020-null-redteam-treated-as-clean.md
- Rationale: Learning-registry Check clauses rewritten to delegate coverage to a test that provides none, silently removing the only guard on the peer-repo mirror.
