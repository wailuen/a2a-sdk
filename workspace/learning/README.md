# Learning index

Entries ordered by LRN number.

| LRN | Description | File |
|-----|-------------|------|
| LRN-001 | Protocol wire tests must verify HTTP headers, not just response bodies | [LRN-001](LRN-001-protocol-wire-tests-check-headers.md) |
| LRN-002 | Pre-release redteam must run at full scope, not wave scope | [LRN-002](LRN-002-pre-release-redteam-full-scope.md) |
| LRN-003 | WWW-Authenticate must include resource_metadata on ALL protected routes | [LRN-003](LRN-003-www-authenticate-resource-metadata-all-routes.md) |
| LRN-004 | CORS preflight (OPTIONS 204) must include Access-Control-Expose-Headers | [LRN-004](LRN-004-cors-preflight-expose-headers.md) |
| LRN-005 | MCP Mcp-Protocol-Version response header must match negotiated body version on initialize | [LRN-005](LRN-005-mcp-version-header-body-sync.md) |
| LRN-006 | ContentModel artifacts must always emit DataPart on A2A, not only when A2UI extension activated | [LRN-006](LRN-006-contentmodel-datapart-always-emit.md) |
| LRN-007 | Bootstrap endpoint is POST /admin/api/keys not POST /admin/bootstrap | [LRN-007](LRN-007-harness-skills-provision-SKILL-md.md) |
| LRN-008 | Source health check uses GET /admin/api/overview, not a per-source POST endpoint | [LRN-008](LRN-008-harness-skills-provision-SKILL-md.md) |
| LRN-009 | Anthropic model backend documented as functional but unimplemented in the SDK | [LRN-009](LRN-009-harness-skills-setup-SKILL-md.md) |
| LRN-010 | SDK bootstrap token is emitted to stderr, not stdout; boot capture must use 2>&1 | [LRN-010](LRN-010-bootstrap-token-emitted-to-stderr.md) |
| LRN-011 | Bootstrap token goes to stderr; agent-verify boot command must use 2>&1 | [LRN-011](LRN-011--Users-wailuen-Development-a2a-sdk-harness-skills-agent-verify-SKILL-md.md) |
| LRN-012 | wave-cycle.js A2UI audit prompt misstated Standard Profile type counts as Core 7 + Extended 11 instead of Core 6 + Extended 8 | [LRN-012](LRN-012-harness-workflows-wave-cycle-js.md) |
| LRN-013 | AC "integration note" wording targets the Integration section, not step bodies | [LRN-013](LRN-013-harness-skills-upgrade-SKILL-md.md) |
| LRN-014 | pytest -q tests/ bypasses addopts ignore exclusions | [LRN-014](LRN-014-pytest-explicit-path-bypasses-addopts.md) |
| LRN-015 | MCP tools/call — emits coercion failure must return isError:True, never except:pass | [LRN-015](LRN-015-mcp-coercion-failure-must-return-iserror.md) |
| LRN-016 | SSRF IP-block logic must live in agent_sdk/common/http.py — never duplicated | [LRN-016](LRN-016-ssrf-single-predicate-common-http.md) |
| LRN-017 | wave-cycle.js — schema-gated gate agents required at redteam and proto-fix checkpoints | [LRN-017](LRN-017-wave-cycle-gate-agents-at-checkpoints.md) |
| LRN-018 | MCP route bypasses per-type wire dispatch, emitting raw field dict instead of markdown string | [LRN-018](LRN-018-mcp-wire-type-dispatch-bypass.md) |
| LRN-019 | Null gate response treated as pass (fail-open) | [LRN-019](LRN-019-null-gate-fail-open.md) |
| LRN-020 | Null redteam response treated as clean pass in unit loop | [LRN-020](LRN-020-null-redteam-treated-as-clean.md) |
| LRN-021 | Shared block flag emits wrong remediation instruction | [LRN-021](LRN-021-shared-flag-misdirected-remediation.md) |
| LRN-022 | Null gate response silently permits archive (fail-open) | [LRN-022](LRN-022-null-gate-fail-open-archive.md) |
| LRN-023 | Null redteam response treated as clean (fail-open) | [LRN-023](LRN-023-null-redteam-fail-open.md) |
| LRN-024 | Proto-fix gate null treated as pass in wave-cycle | [LRN-024](LRN-024-proto-fix-gate-null-fail-open.md) |
| LRN-025 | Null agent response in archive commit guard silently passes as clean | [LRN-025](LRN-025-null-agent-fail-open-archive-guard.md) |
| LRN-026 | Null proto-fix gate fails open — crashed gate must set protocolBlocked | [LRN-026](LRN-026-null-gate-fails-open.md) |
| LRN-027 | Hardcoded seam-audit route paths bypass dynamic allCreates derivation | [LRN-027](LRN-027-hardcoded-seam-route-paths.md) |
| LRN-028 | Redteam findingsCount can contradict findings array, bypassing zero-tolerance gate | [LRN-028](LRN-028-redteam-findings-count-mismatch.md) |
| LRN-029 | Null gate crash allows fail-open progression in fix loops | [LRN-029](LRN-029-null-gate-fail-open-loop.md) |
| LRN-030 | Null redteam response silently treated as clean pass | [LRN-030](LRN-030-null-redteam-fail-open.md) |
| LRN-031 | Null pytest gate response treated as GREEN (fail-open) | [LRN-031](LRN-031-null-gate-fail-open.md) |
| LRN-032 | Archive-blocked log message must distinguish test failure from protocol block | [LRN-032](LRN-032-archive-block-message-misdirection.md) |
| LRN-033 | Wave-cycle missing re-gate after test-fix dispatch | [LRN-033](LRN-033-wave-cycle-test-fix-missing-regate.md) |
| LRN-034 | Unconditional seam audit fires on every protocol wave | [LRN-034](LRN-034-unconditional-seam-audit-no-guard.md) |
| LRN-035 | Test-fix agent result must be verified with a re-gate pytest pass | [LRN-035](LRN-035-test-fix-agent-missing-regate-verify.md) |
| LRN-036 | Phase redteam null-response must not reset prevSigs | [LRN-036](LRN-036-phase-redteam-null-must-not-reset-prevsigs.md) |
| LRN-037 | Protocol test-fix path missing re-gate before recheck | [LRN-037](LRN-037-proto-testfix-missing-regate.md) |
| LRN-038 | → Consolidated into LRN-034 (unconditional seam audit dispatch) | [LRN-038](LRN-038-unconditional-seam-audit-dispatch.md) |
| LRN-039 | SC-F1 emits annotation validator must skip — not raise — when eval_str resolution fails | [LRN-039](LRN-039-sc-f1-emits-annotation-unresolvable-string-skip.md) |
| LRN-040 | Deterministic THREAD_ID in acceptance-api.js causes concurrent-run contamination | [LRN-040](LRN-040-thread-id-acceptance-api-contamination-risk.md) |
| LRN-041 | Protocol-fix loop missing re-gate before recheck | [LRN-041](LRN-041-proto-fix-loop-missing-regate-before-recheck.md) |
| LRN-042 | buildScenarioPrompt silently drops followUpTurns via JS destructuring default | [LRN-042](LRN-042-buildscenariopromt-followupturns-silent-drop.md) |
| LRN-043 | openWorldHint must be derived from SourceAdapter backing, not tier or read_only | [LRN-043](LRN-043-mcp-tier1-tools-openworldhint-missing.md) |
| LRN-044 | ValidationError swallowed by catch-all loop — SI-2 requires explicit enrichment | [LRN-044](LRN-044-validationerror-swallowed-in-catch-all.md) |
| LRN-045 | JSON parse failure must return -32700, not -32602 (invalid-params) | [LRN-045](LRN-045-json-parse-error-wrong-jsonrpc-code.md) |
| LRN-046 | A2UI DataPart emitted unconditionally — requires X-A2A-Extensions opt-in gate | [LRN-046](LRN-046-a2ui-datapart-emitted-without-extension-optin.md) |
| LRN-047 | Terminal re-message rule violated — _continue_from_terminal creates new task instead of returning error | [LRN-047](LRN-047-terminal-re-message-creates-task-instead-of-error.md) |
| LRN-048 | Inbound Message mutated with server-assigned taskId/contextId before archiving in history | [LRN-048](LRN-048-inbound-message-contextid-mutation-in-history.md) |
| LRN-049 | AG-UI CUSTOM events wrongly gated on catalog membership — must emit freely | [LRN-049](LRN-049-agui-custom-emit-freely-catalog-gate-wrong.md) |
| LRN-050 | CLAUDE.md/gitignore consistency gap | [LRN-050](LRN-050-claudemd-gitignore-consistency-gap.md) |
| LRN-051 | uv --no-dev is a silent no-op on extras-only dependency layouts | [LRN-051](LRN-051-uv-no-dev-silent-noop-on-extras-only-layouts.md) |
| LRN-052 | gitignored/untracked path cannot land in a wave todo | [LRN-052](LRN-052-gitignored-path-cannot-land-in-wave-todo.md) |
| LRN-053 | wave scope must union Creates: AND Modifies: paths | [LRN-053](LRN-053-wave-scope-must-union-creates-and-modifies.md) |
| LRN-054 | Dockerfile lockfile COPY requires lockfile-producer todos in same wave | [LRN-054](LRN-054-dockerfile-lockfile-producer-consumer-coupling.md) |
| LRN-055 | gitignore placed in wrong directory fails to protect credential files | [LRN-055](LRN-055-gitignore-wrong-directory-scope.md) |
| LRN-056 | Wave todo path under gitignored/untracked tree is silently undeliverable | [LRN-056](LRN-056-gitignored-tree-todo-path.md) |
| LRN-057 | uv sync extra flags are not additive across invocations | [LRN-057](LRN-057-uv-sync-extras-not-additive.md) |
| LRN-058 | Duplicate LRN ID orphans one learning from the redteam check loop | [LRN-058](LRN-058-duplicate-lrn-id-orphans-learning.md) |
| LRN-059 | Wave scope derived from Creates-only silently bypasses review for modify-only waves | [LRN-059](LRN-059-wave-scope-creates-only-bypass.md) |
| LRN-060 | Wave-runner scope fix not propagated to sibling runners | [LRN-060](LRN-060-wave-runner-scope-fix-not-propagated.md) |
| LRN-061 | Credential gitignore globs missing from secondary scaffold path | [LRN-061](LRN-061-scaffold-gitignore-partial-coverage.md) |
| LRN-062 | Wave archive silently skips plan.md when no pre-seeded row exists | [LRN-062](LRN-062-wave-archive-missing-row-append.md) |
| LRN-063 | Null gate response fails open in wave-cycle archive path | [LRN-063](LRN-063-null-gate-fail-open-wave.md) |
| LRN-064 | Comment claiming guard is not a control-flow guard | [LRN-064](LRN-064-comment-only-control-flow-guard.md) |
| LRN-065 | Runtime and template workflow copies diverge silently | [LRN-065](LRN-065-workflow-runtime-template-drift.md) |
| LRN-066 | Learning narrative must match landed code at codify time | [LRN-066](LRN-066-learning-narrative-code-drift.md) |
| LRN-067 | Wave state split-brain — plan.md and todo file disagree on critical item status | [LRN-067](LRN-067-wave-state-split-brain.md) |
| LRN-068 | Phase redteam scores ACs against unimplemented wave targets | [LRN-068](LRN-068-phase-redteam-empty-diff-false-pass.md) |
| LRN-069 | uv sync without --extra dev breaks pytest steps | [LRN-069](LRN-069-uv-sync-missing-dev-extra-before-pytest.md) |
| LRN-070 | uv sync without --extra dev omits test deps and breaks pytest | [LRN-070](LRN-070-uv-sync-missing-extra-dev-drops-pytest.md) |
| LRN-071 | template/ is a peer repo — wave todos must commit+push to wailuen/a2a-agent-template, not to a2a-sdk | [LRN-071](LRN-071-template-is-peer-repo-not-submodule.md) |
| LRN-072 | git add on a directory containing .git creates a gitlink (mode 160000), not file tracking | [LRN-072](LRN-072-git-add-nested-repo-creates-gitlink-not-files.md) |
| LRN-073 | Scenario runner filter(Boolean) turns crashed agents into silent pass-rate inflation | [LRN-073](LRN-073-acceptance-filter-boolean-nan-denominator.md) |
| LRN-074 | inspect.get_annotations collapses explicit `-> None` and missing annotation to the same value | [LRN-074](LRN-074-inspect-get-annotations-none-ambiguity.md) |
| LRN-075 | Harness workflow fixes don't propagate to template peer repo | [LRN-075](LRN-075-harness-workflow-template-sync-gap.md) |
| LRN-076 | Wave redteam fix loop must invoke debug agent unconditionally at round 4+ — not only on stall | [LRN-076](LRN-076-redteam-loop-must-call-debug-at-round-4.md) |
| LRN-077 | Wire-up fixes in build_app() need their own integration test at the app.state seam | [LRN-077](LRN-077-build-app-wire-up-needs-integration-test.md) |
| LRN-078 | Admin-form field additions must appear in the todo Modifies: list | [LRN-078](LRN-078-admin-form-touch-must-appear-in-modifies.md) |
| LRN-079 | LRN Check clause grepping non-existent path is a fail-open guard | [LRN-079](LRN-079-check-clause-dead-path-fail-open.md) |
| LRN-080 | LRN Fix snippet must be copied from landed code, not the originally proposed fix | [LRN-080](LRN-080-fix-snippet-differs-from-landed-code.md) |
| LRN-081 | Store-sourced credential written to os.environ leaks to subprocesses | [LRN-081](LRN-081-store-secret-env-mutation.md) |
| LRN-082 | A2A probes using only mimeType miss ContentModel DataPart content-type signals | [LRN-082](LRN-082-probe-mimeType-only-content-signal.md) |
| LRN-083 | Reverse HTTP→A2A error map must not attribute generic 404s to TaskNotFound | [LRN-083](LRN-083-reverse-http-a2a-error-map-over-attribution.md) |
| LRN-084 | Dependency floor too low — mocked tests hide AttributeError on permitted versions | [LRN-084](LRN-084-dependency-floor-symbol-missing.md) |
| LRN-085 | Wave todos touching harness/workflows/*.js must list the template/.claude/workflows/ peer-repo runtime copy as a deliverable | [LRN-085](LRN-085-harness-workflow-js-must-list-template-peer-copy.md) |
| LRN-086 | Companion SKILL.md re-documents broken wire protocol after workflow fix | [LRN-086](LRN-086-skill-companion-protocol-drift.md) |
| LRN-087 | MCP serverInfo.title conservatively gated at 2025-11-25, not 2025-06-18 where spec adds it | [LRN-087](LRN-087-mcp-serverinfo-title-conservative-gate.md) |
| LRN-088 | Inbound client Message mutated with server-assigned IDs before history storage | [LRN-088](LRN-088-inbound-message-mutation.md) |
| LRN-089 | MCP version gate missing initialize carve-out in legacy handler | [LRN-089](LRN-089-mcp-version-gate-missing-initialize-carveout.md) |
| LRN-090 | Protocol route rename leaves reference binding table stale | [LRN-090](LRN-090-protocol-route-rename-reference-table-drift.md) |
| LRN-091 | MCP serverInfo.title version gate is conservatively correct — deliberate deviation from spec baseline | [LRN-091](LRN-091-mcp-serverinfo-title-version-gate.md) |
| LRN-092 | OAuth token endpoint does not enforce RFC 8707 resource param | [LRN-092](LRN-092-oauth-token-endpoint-resource-param-enforcement.md) |
| LRN-093 | AG-UI route missing Content-Type enforcement unlike A2A and MCP | [LRN-093](LRN-093-content-type-enforcement-uniformity.md) |
| LRN-094 | Agent card advertises tools absent from MCP tools/list | [LRN-094](LRN-094-card-mcp-surface-mismatch.md) |
| LRN-095 | Test-first test shipped RED — wave archived without passing its own AC | [LRN-095](LRN-095-test-first-red-gate-bypass.md) |
| LRN-096 | Workflow({name, args}) drops args — named-workflow resolver has undefined args global | [LRN-096](LRN-096-workflow-named-args-dropped.md) |
| LRN-097 | AgentExtension URIs must use https:// scheme — URN-scheme URIs are silently dropped | [LRN-097](LRN-097-agent-extension-uri-must-be-https.md) |
| LRN-098 | Scheduler-as-lifespan-extra pattern — import agent_sdk.scheduler does not exist | [LRN-098](LRN-098-scheduler-as-lifespan-extra-pattern.md) |
| LRN-099 | A2A REST action suffix can differ from the JSON-RPC method name | [LRN-099](LRN-099-a2a-rest-suffix-differs-from-method-name.md) |
| LRN-100 | Budget-exhausted deferred marker must be relocated once findings are resolved | [LRN-100](LRN-100-budget-exhausted-deferred-must-be-relocated.md) |
| LRN-101 | Agent card description must never fall back to empty string | [LRN-101](LRN-101-agent-card-description-empty-string-fallback.md) |
| LRN-102 | TOOL_PROGRESS CUSTOM event emitted in ag_ui.py but absent from CUSTOM_EVENTS tuple, card schema,... | [LRN-102](LRN-102-tool-progress-custom-event-parity-gap.md) |
| LRN-103 | A2A multi-turn continuation must use contextId, not taskId, for completed tasks | [LRN-103](LRN-103-a2a-multiturn-contextid-continuation.md) |
| LRN-104 | deferred imports in model clients must not be silently caught by bare except Exception | [LRN-104](LRN-104-deferred-import-silent-wrap.md) |
| LRN-105 | bare "except Exception" in model client invoke paths swallows distinct error categories (e.g. Rat... | [LRN-105](LRN-105-broad-except-swallows-error-category.md) |
| LRN-106 | caplog assertions on agent_sdk.* loggers false-green outside full-suite order | [LRN-106](LRN-106-caplog-propagate-false-order-dependent.md) |
| LRN-107 | Fixed broken test idiom recurs uncaught in a sibling test | [LRN-107](LRN-107-duplicated-broken-test-idiom.md) |
| LRN-108 | Unautomated documentation anchors drift silently | [LRN-108](LRN-108-unautomated-doc-anchor-drift.md) |
| LRN-109 | Documented ledger-append fix (LRN-062) recurred unenforced in w029 | [LRN-109](LRN-109-wave-ledger-guard-not-enforced.md) |
| LRN-110 | Required-but-nullable field silently dropped by blanket exclude_none | [LRN-110](LRN-110-required-nullable-field-dropped-by-exclude-none.md) |
| LRN-111 | AG-UI Interrupt.expiresAt wire format — ISO-8601 citation and verification method | [LRN-111](LRN-111-agui-interrupt-expires-at-wire-format-citation.md) |
| LRN-112 | Monotonic clock value fed to datetime.fromtimestamp() as if it were epoch time | [LRN-112](LRN-112-monotonic-clock-epoch-confusion.md) |
| LRN-113 | New abstractmethod on public ABC breaks external subclasses | [LRN-113](LRN-113-public-abc-new-abstractmethod.md) |
| LRN-114 | Non-total content extraction crashes AG-UI SSE stream without terminal frame | [LRN-114](LRN-114-non-total-sse-validation-crash.md) |
| LRN-115 | AG-UI _capabilities() fail-closed tier="none" default is intentional — do not "align" it to spec's tier="core | [LRN-115](LRN-115-agui-capabilities-fail-closed-tier-none-default.md) |
| LRN-116 | MCP tools/call bypasses generator tool dispatch, breaking long-running Tier-1 tools | [LRN-116](LRN-116-mcp-tools-call-bypasses-generator-dispatch.md) |
| LRN-117 | Allowlist must cover LLM system-prompt teaching surface | [LRN-117](LRN-117-allowlist-must-cover-llm-teaching-surface.md) |
| LRN-118 | DESIGN.md MCP version-header rule stale after transport split | [LRN-118](LRN-118-protocol-doc-behavior-drift.md) |
| LRN-119 | Mid-wave module extraction omitted from Creates: ships unimportable pkg | [LRN-119](LRN-119-mid-wave-module-extraction-untracked.md) |
| LRN-120 | MCP tools/call folds unhandled DeferredResult via str(), leaking repr | [LRN-120](LRN-120-unhandled-deferred-result-leak.md) |
| LRN-121 | Codified LRN Check exists as text but isn't wired into an enforced gate | [LRN-121](LRN-121-lrn-check-not-enforced-gate.md) |
| LRN-122 | DeferredResult detection must run on every tool-result path in loop.py, not just the coroutine branch | [LRN-122](LRN-122-loop-deferred-detection-must-cover-generator-branch.md) |
| LRN-123 | task.artifacts must be appended AFTER the wire frame serializes, not before | [LRN-123](LRN-123-artifact-append-must-follow-serialize.md) |
| LRN-124 | Archive note describing a redteam fix must cover the full landed diff, not just its headline AC | [LRN-124](LRN-124-archive-note-must-cover-full-redteam-diff.md) |
| LRN-125 | Terminal-artifact guard caught build/wire exceptions but not non-serializable payloads | [LRN-125](LRN-125-artifact-guard-serializability-gap.md) |
| LRN-126 | CSP form-action must be widened on the form-owning document, not the redirect | [LRN-126](LRN-126-csp-form-action-wrong-response.md) |
| LRN-127 | CSP directive injection via raw redirect_uri netloc interpolation | [LRN-127](LRN-127-header-injection-via-raw-netloc.md) |
| LRN-128 | SI-tagged AC landed without its mandated regression test | [LRN-128](LRN-128-si-ac-missing-named-test.md) |
| LRN-129 | Import gate only resolves absolute imports, misses relative | [LRN-129](LRN-129-import-gate-relative-import-blind-spot.md) |
| LRN-130 | Relative direct-module import form skipped submodule check, false-positive-blocked archive | [LRN-130](LRN-130-import-resolution-form-parity.md) |
| LRN-131 | Cross-runner gate logic diverges when a fix lands in only one runner | [LRN-131](LRN-131-cross-runner-gate-logic-divergence.md) |
| LRN-132 | Protocol surface classification must follow code sharing, not directory naming | [LRN-132](LRN-132-protocol-surface-classification-by-blast-radius.md) |
| LRN-133 | Reversing a decision must supersede its learning's Check in the same wave | [LRN-133](LRN-133-learning-check-reversal-reconciliation.md) |
| LRN-134 | A2UI-over-A2A DataPart "messages" wrapper key satisfies A2A v0.3.0 but contradicts A2UI v0.9.1's own literal binding — citation + known interop caveat | [LRN-134](LRN-134-a2ui-a2a-datapart-messages-key-not-spec-mandated.md) |
| LRN-135 | Portable spec oracle rewritten to teach SDK-private deviation as canonical rule | [LRN-135](LRN-135-portable-oracle-encodes-deviation.md) |
| LRN-136 | Phase Redteam duplicates Unit Redteam on single-group waves — skip when groups.length === 1 | [LRN-136](LRN-136-phase-redteam-single-group-duplicate-pass.md) |
| LRN-137 | Wave-runner fixes land in wave-cycle.js copies but skip sibling sdk-wave.js | [LRN-137](LRN-137-cross-runner-fix-port-gap.md) |
| LRN-138 | reuse_fields_for_model crashes on get_type_hints for locally-scoped pydantic models | [LRN-138](LRN-138-local-scope-get-type-hints-crash.md) |
| LRN-139 | Deferred tool handoff leaves dangling toolUse with no matching toolResult | [LRN-139](LRN-139-deferred-handoff-dangling-tooluse.md) |
| LRN-140 | Base-class security contract fixed on 2/14 subclasses, no completeness gate | [LRN-140](LRN-140-partial-rollout-of-base-class-security-contract.md) |
| LRN-141 | Reuses:C-NNN annotation treated as behavior match instead of landing-location binding | [LRN-141](LRN-141-reuses-annotation-wrong-location.md) |
| LRN-142 | Reuse-mismatch error text names its own bypass token to the model | [LRN-142](LRN-142-validation-error-must-not-name-bypass.md) |
| LRN-143 | Optional ReuseKind field permanently rejects explicit None as a raw mismatch | [LRN-143](LRN-143-optional-field-none-treated-as-raw-value.md) |
| LRN-144 | Transcript role-alternation invariant not enforced outside run_loop's own exit points | [LRN-144](LRN-144-transcript-bridge-must-cover-out-of-loop-writers.md) |
| LRN-145 | Changelog entries must land under Unreleased, not inside an already-tagged release section | [LRN-145](LRN-145-changelog-tagged-release-rewrite.md) |
| LRN-146 | Reuse gate keys on Python field name, not wire alias | [LRN-146](LRN-146-field-alias-key-mismatch-fail-open.md) |
| LRN-147 | Peer-repo deliverable declared in a wave todo closed without its own commit existing | [LRN-147](LRN-147-peer-repo-completion-gate-missing.md) |
| LRN-148 | Non-user-facing status frame re-serializes stale status.message | [LRN-148](LRN-148-stale-status-message-reserialized.md) |
| LRN-149 | Cross-turn reuse index needs transport history fold with tool results | [LRN-149](LRN-149-transport-fold-drops-tool-results.md) |
| LRN-150 | Cross-turn index seeded from newest-terminal-task-only decays after one hop | [LRN-150](LRN-150-cross-turn-index-single-hop-decay.md) |
| LRN-151 | Early return above a bounded-recovery counter exempts that rejection path from the guarantee | [LRN-151](LRN-151-early-return-bypasses-bounded-recovery-counter.md) |
| LRN-152 | Presence-only meta-test misses per-field sanitisation gaps | [LRN-152](LRN-152-presence-only-sanitizer-meta-test.md) |
| LRN-153 | Breaking changes filed under the wrong CHANGELOG heading forfeit the §4.0 exemption | [LRN-153](LRN-153-breaking-change-heading-misclassification.md) |
| LRN-154 | LRN-133 gate excludes non-wave GH fixes | [LRN-154](LRN-154-check-reconciliation-scope-gap.md) |
| LRN-155 | prose field skipped GH-130 sanitization applied to its render-method siblings | [LRN-155](LRN-155-partial-sanitization-coverage-gap.md) |
| LRN-156 | Hard cost backstop must ship with operator-reachable override | [LRN-156](LRN-156-hard-backstop-needs-override-escape-hatch.md) |
| LRN-157 | Parametrize helper drops missing mirror-repo paths | [LRN-157](LRN-157-mirror-path-silent-filter.md) |
| LRN-158 | Single-line sanitizer applied to a multi-line markdown field corrupts it | [LRN-158](LRN-158-delimiter-sanitizer-multiline-corruption.md) |
| LRN-159 | Byte-identical sync guard spans only wave-cycle.js mirrors, blind to sdk-wave.js | [LRN-159](LRN-159-cross-runner-port-gate-unenforced.md) |
| LRN-160 | Files named only in Reuses:/SI: prose evade wave scope and all gates | [LRN-160](LRN-160-prose-only-scope-declaration-gap.md) |
| LRN-161 | xfail(strict=True) absorbs unverifiable state, doesn't block archive | [LRN-161](LRN-161-xfail-strict-not-archive-gate.md) |
| LRN-162 | Wave runs template/ deliverable with no template/ checkout | [LRN-162](LRN-162-peer-repo-checkout-missing.md) |
| LRN-163 | Sync guard blind to cross-runner gate drift (wave-cycle.js vs sdk-wave.js) | [LRN-163](LRN-163-sync-guard-cross-runner-blind-spot.md) |
| LRN-164 | Round-cap exit drops severity-floor findings without deferred note | [LRN-164](LRN-164-severity-floor-exit-durability-gap.md) |
| LRN-165 | Unit round-cap exit skips codify capture, archive block | [LRN-165](LRN-165-budget-exit-bypasses-capture-and-gate.md) |
| LRN-166 | Text gate parser has quote and multi-fence blind spots | [LRN-166](LRN-166-gate-parser-blind-spot.md) |
| LRN-167 | Cost backstop default must scale with wave shape | [LRN-167](LRN-167-undersized-fixed-cost-backstop.md) |
| LRN-168 | Todo Creates/Modifies omits an actually-touched tracked file | [LRN-168](LRN-168-todo-omits-modified-file.md) |
| LRN-169 | Security contract documented on private docstring, not public authoring guide | [LRN-169](LRN-169-teaching-surface-security-gap.md) |
| LRN-170 | Round-cap durability fix (LRN-164) unported to sdk-wave.js | [LRN-170](LRN-170-round-cap-fix-unported.md) |
| LRN-171 | Renderer delimiter contract applied to the wrapped field but not its same-line neighbor | [LRN-171](LRN-171-delimiter-contract-same-line-neighbor-gap.md) |
| LRN-172 | Round-budget loop exits skip archive-blocking flags (fail-open) | [LRN-172](LRN-172-round-budget-exit-fail-open.md) |
| LRN-173 | Reused wave ID collides with completed/ basename and clobbers history | [LRN-173](LRN-173-wave-id-basename-collision.md) |
| LRN-174 | Wave executes with a declared template/ deliverable it cannot reach | [LRN-174](LRN-174-unrunnable-peer-repo-deliverable.md) |
| LRN-175 | Terminal exception handlers lack already-terminal guard present on other writers | [LRN-175](LRN-175-terminal-except-handler-missing-guard.md) |
| LRN-176 | Todo checked [x] with a "Landed:" note despite an unenacted peer-repo diff | [LRN-176](LRN-176-todo-marked-complete-unverified.md) |
| LRN-177 | Actionable errors need reachability tests, not raise-site unit tests | [LRN-177](LRN-177-actionable-error-reachability-gap.md) |
| LRN-178 | Cross-client invariant lapses when fixed in only one model client | [LRN-178](LRN-178-cross-client-guard-gap.md) |
| LRN-179 | Exemption citations must be verified against file location, not asserted | [LRN-179](LRN-179-unverified-exemption-citation.md) |
| LRN-180 | Wave scope extraction drops paths embedded in Creates:/Modifies: prose | [LRN-180](LRN-180-wave-scope-prose-extraction.md) |
| LRN-181 | Runner protocol-surface arrays hardcoded to one repo's dialect | [LRN-181](LRN-181-protocol-surface-dialect-mismatch.md) |
| LRN-182 | Ported gate keeps wrong runner's source-root path dialect | [LRN-182](LRN-182-gate-port-source-dialect-mismatch.md) |
| LRN-183 | Delimiter-safety fix missed renderer-owned separators | [LRN-183](LRN-183-renderer-owned-delimiter-enumeration-gap.md) |
| LRN-184 | Ported gate logic keeps source runner's source-root literal, not destination's | [LRN-184](LRN-184-gate-porting-root-dialect-drift.md) |
| LRN-185 | Mandatory third-party sanitiser contract points at an unexported private helper | [LRN-185](LRN-185-unexported-helper-mandatory-contract.md) |
| LRN-186 | Protocol advisor filter(Boolean) drops null results (fail-open) | [LRN-186](LRN-186-protocol-advisor-filter-boolean-fail-open.md) |
| LRN-187 | Doc-file AC verified against working tree, not the landing commit | [LRN-187](LRN-187-doc-ac-checked-against-working-tree.md) |
| LRN-188 | Grep-path guard blind to backslash-continued commands | [LRN-188](LRN-188-grep-continuation-blind-spot.md) |
| LRN-189 | isinstance-check helper without TypeGuard breaks mypy narrowing | [LRN-189](LRN-189-helper-missing-typeguard-annotation.md) |
| LRN-190 | Single-pop repair doesn't re-check the invariant it was fixing | [LRN-190](LRN-190-single-pass-repair-leaves-second-violation.md) |
| LRN-191 | Hardcoded MCP protocol-version literal drifts from the real source of truth | [LRN-191](LRN-191-hardcoded-protocol-version-outside-source-of-truth.md) |
| LRN-192 | Check clause delegates coverage to a test that never actually runs | [LRN-192](LRN-192-check-vacuous-test-delegation.md) |
| LRN-193 | Generator finally is not a lifecycle hook for pre-stream admission slots | [LRN-193](LRN-193-generator-finally-not-a-lifecycle-hook.md) |
| LRN-194 | Identity-scoped error-code split lacks foreign-identity test | [LRN-194](LRN-194-identity-scoped-error-code-oracle.md) |
| LRN-195 | Wire error code change must reconcile every learning/skill narrative | [LRN-195](LRN-195-wire-error-code-change-narrative-sweep.md) |
| LRN-196 | TTL backstop reclaims a still-live concurrency-cap slot under load | [LRN-196](LRN-196-ttl-reclaims-live-concurrency-slot.md) |
| LRN-197 | Error-code change lands without sweeping docs that pin the old code | [LRN-197](LRN-197-error-code-doc-sweep-gap.md) |
| LRN-198 | Concurrency cap applied to one stream route, sibling route left uncapped | [LRN-198](LRN-198-uncapped-sibling-stream-route.md) |
| LRN-199 | Wire error/status code change ships with zero CHANGELOG entry | [LRN-199](LRN-199-changelog-omits-wire-code-change.md) |
| LRN-200 | Backstop reaper reclaims only half of a release surface | [LRN-200](LRN-200-partial-release-backstop-reaper.md) |
| LRN-201 | CHANGELOG exemption claims need a spec citation, not prose | [LRN-201](LRN-201-changelog-exemption-audit-conflict.md) |
| LRN-202 | Public API change lands outside declared todo/CHANGELOG scope | [LRN-202](LRN-202-unscoped-public-api-change.md) |
| LRN-203 | Safety invariant lives in one ABC subclass, not contracted | [LRN-203](LRN-203-undeclared-abc-safety-contract.md) |
| LRN-204 | Sync BackgroundTask closures race event-loop state off-thread | [LRN-204](LRN-204-background-task-sync-closure.md) |
| LRN-205 | Two-condition exemption citation accepted without verifying either condition | [LRN-205](LRN-205-exemption-condition-verification-gap.md) |
| LRN-206 | Route safety invariant relies on one ABC subclass, not the contract | [LRN-206](LRN-206-abc-single-impl-invariant.md) |
| LRN-207 | Git-dirty file outside declared scope escapes review | [LRN-207](LRN-207-dirty-tree-file-outside-declared-scope.md) |
| LRN-208 | Authoring SKILL.md fixed, sibling copies left stale | [LRN-208](LRN-208-mirrored-skill-copy-drift.md) |
| LRN-209 | 429 tests assert status_code only, missing headers and body redaction | [LRN-209](LRN-209-status-code-only-429-assertion.md) |
| LRN-210 | Registration-scoped identity used as per-user quota key | [LRN-210](LRN-210-registration-scoped-identity-as-user-quota-key.md) |
| LRN-211 | Admission cap wired into one router module, sibling module's streams left unbounded | [LRN-211](LRN-211-admission-budget-module-scope-gap.md) |
| LRN-212 | Breaking CHANGELOG entry must move version/todos/register together | [LRN-212](LRN-212-release-state-artifact-desync.md) |
| LRN-213 | Live-subscriber eviction guard was added at one call site, not as the store's invariant | [LRN-213](LRN-213-eviction-guard-fixed-one-call-site-not-the-invariant.md) |
| LRN-214 | Catch-all logs raw ValidationError via logger.exception | [LRN-214](LRN-214-catchall-logs-validation-error-message.md) |
| LRN-215 | Unit Redteam reviewed groups one at a time despite planner-guaranteed disjoint scope — run concurrently with a gate mutex | [LRN-215](LRN-215-unit-redteam-groups-run-concurrently.md) |
| LRN-216 | Wrapper exception must not echo str(wrapped ValidationError) | [LRN-216](LRN-216-wrapper-exception-str-interpolation-leak.md) |
| LRN-217 | Row-fabrication guard neutralised only CR/LF, missing Unicode/C0 breaks | [LRN-217](LRN-217-row-fabrication-partial-linebreak-neutralization.md) |
| LRN-218 | Resolved-marker block skips JSON normalization, poisons message history | [LRN-218](LRN-218-unnormalized-marker-value-poisons-messages.md) |
| LRN-219 | Deferred background awaiter leaks raw Reusable wrapper onto the wire | [LRN-219](LRN-219-wrapper-unwrap-missing-dispatch-surface.md) |
| LRN-220 | New zero-tolerance exits can bypass one-sided count/array guards | [LRN-220](LRN-220-asymmetric-count-reconciliation-guard.md) |
| LRN-221 | Bare catch-all on tool-dispatch path must log exception type, not just fixed string | [LRN-221](LRN-221-bare-except-swallows-exception-type.md) |
| LRN-222 | New model-client constructor kwarg added without settings field or seam wiring | [LRN-222](LRN-222-unwired-client-constructor-kwarg.md) |
| LRN-223 | Shared input_schema advertises loop-only $ref: affordance to MCP and agent-card surfaces | [LRN-223](LRN-223-shared-schema-advertises-unimplemented-affordance.md) |
| LRN-224 | SI regression test hit one surface, not the Reuses-mandated set | [LRN-224](LRN-224-si-test-partial-surface-coverage.md) |
| LRN-225 | Terminal exception handlers skip dangling tool_use repair | [LRN-225](LRN-225-dangling-tool-use-terminal-handler.md) |
| LRN-226 | skipif on a failing guard silences the regression it exists to catch | [LRN-226](LRN-226-guard-skip-silences-failing-regression-check.md) |
| LRN-227 | Schema required-key added without syncing agent contract | [LRN-227](LRN-227-schema-contract-doc-drift.md) |
| LRN-228 | Gate ported to the runner where it can never fire | [LRN-228](LRN-228-gate-placement-wrong-runner.md) |
| LRN-229 | Quality-gate exit-condition change left SKILL.md docs frozen at old contract | [LRN-229](LRN-229-gate-contract-doc-drift.md) |
| LRN-230 | Version bump written while branch is behind origin's tag lineage | [LRN-230](LRN-230-version-bump-ignores-ancestry.md) |
| LRN-231 | Wave archive note verified against working tree, not the landed commit | [LRN-231](LRN-231-archive-note-checked-against-working-tree.md) |
| LRN-232 | pyproject version and CHANGELOG heading disagree, both collide with real tags | [LRN-232](LRN-232-changelog-pyproject-version-mismatch.md) |
| LRN-233 | New hook name collides with a pre-existing private method, breaks import | [LRN-233](LRN-233-hook-name-collision-breaks-legal-prior-code.md) |
| LRN-234 | Frozen conformance profile loosened to make own code pass, unratified | [LRN-234](LRN-234-frozen-oracle-loosened-to-fit-own-code.md) |
| LRN-235 | PEP 649 breaks raw __annotations__ "declared-here" check | [LRN-235](LRN-235-pep649-declared-here-annotations.md) |
| LRN-236 | Landed C-NNN component leaves inline duplicate + stale registry status | [LRN-236](LRN-236-landed-component-inline-duplicate-drift.md) |
| LRN-237 | Guarded repair wrapper conflates in-memory failure with flush-only failure | [LRN-237](LRN-237-repair-wrapper-conflates-failure-modes.md) |
| LRN-238 | Exception class name interpolated into wire-facing tool error text | [LRN-238](LRN-238-exception-class-name-wire-leak.md) |
| LRN-239 | Voluntary stable-core break shipped under a patch version bump | [LRN-239](LRN-239-patch-bump-hides-stable-core-break.md) |
| LRN-240 | Durable write hook wired only into repair path, not happy-path completion | [LRN-240](LRN-240-terminal-write-hook-happy-path-gap.md) |
| LRN-241 | Hand-listed text fallback silently drops wire fields added later | [LRN-241](LRN-241-hand-listed-text-fallback-field-drift.md) |
| LRN-242 | Conformance failure resolved by editing the portable oracle, not the code | [LRN-242](LRN-242-editing-conformance-oracle-to-pass.md) |
| LRN-243 | New terminal-status flush marks tasks terminal before transcript persists | [LRN-243](LRN-243-terminal-status-flush-outpaces-contract.md) |
| LRN-244 | Shared helper's new raising hook guarded at one call site, not all | [LRN-244](LRN-244-shared-helper-guard-not-reaudited-all-callers.md) |
| LRN-245 | Re-resolving a label to a new value appends a second index entry, deadlocking $ref | [LRN-245](LRN-245-resolved-index-label-append-deadlock.md) |
| LRN-246 | Hoisting metadata onto ContentModel silently dropped it from a _Wire sub-shape | [LRN-246](LRN-246-non-contentmodel-metadata-field-loss.md) |
| LRN-247 | Unconditional dict-strip on model_dump() crashes for RootModel/list-shaped dumps | [LRN-247](LRN-247-non-dict-model-dump-strip-crash.md) |
| LRN-248 | LRN-044 regression — a remediation sweep left one bare except unlogged | [LRN-248](LRN-248-partial-bare-except-remediation-sweep.md) |
| LRN-249 | LRN-144 Check failure — legitimate second bridge call site left the LRN unamended | [LRN-249](LRN-249-unamended-call-site-invariant-drift.md) |
| LRN-250 | Template-method adoption shim recurses on concrete-subclass super() calls | [LRN-250](LRN-250-template-method-adoption-recursion.md) |
| LRN-251 | Wave self-ratified a cross-identity data-exposure policy as documented design | [LRN-251](LRN-251-wave-self-ratifies-security-policy.md) |
| LRN-252 | Wave resolved one contract divergence by deletion and an identical one by widening the frozen spec | [LRN-252](LRN-252-wave-amends-frozen-protocol-contract.md) |
| LRN-253 | Gate/budget fixes skip sdk-wave.js, again | [LRN-253](LRN-253-unported-runner-fix-recurrence.md) |
| LRN-254 | Context-message cap silently drops entire transcript instead of truncating | [LRN-254](LRN-254-silent-context-cap-drops-transcript.md) |
| LRN-255 | Same-wave Check reconciliation sweeps miss sibling LRNs | [LRN-255](LRN-255-incomplete-check-reconciliation-sweep.md) |
| LRN-256 | Wave run on a branch behind origin re-fixes shipped issues | [LRN-256](LRN-256-wave-base-branch-behind-origin.md) |
| LRN-257 | Root config files invisible to all four archive-gate clauses | [LRN-257](LRN-257-root-config-blind-spot.md) |
| LRN-258 | Parse-phase hard-abort gate leaves wave permanently unresumable | [LRN-258](LRN-258-hard-abort-gate-no-escape-hatch.md) |
| LRN-259 | Wave scope extraction accepts directory/glob tokens | [LRN-259](LRN-259-scope-extraction-accepts-directory-glob-tokens.md) |
| LRN-260 | Todo-requested registry/REVIEWS updates not verified by redteam | [LRN-260](LRN-260-registry-update-unchecked.md) |
| LRN-261 | Ratification gate keyed to bare SIGNED OFF text | [LRN-261](LRN-261-signoff-text-only-gate.md) |
| LRN-262 | Sign-off gate substring-matches whole section, never flips | [LRN-262](LRN-262-whole-section-substring-gate.md) |
| LRN-263 | Tests enforce frozen-contract edit while ratification flag False | [LRN-263](LRN-263-unratified-oracle-edit-tests.md) |
| LRN-264 | Advisor docs say Ratified while REVIEWS says unratified | [LRN-264](LRN-264-advisor-status-disagreement.md) |
| LRN-265 | Ratification flag computed but never branched on by tests | [LRN-265](LRN-265-unused-ratification-flag.md) |
| LRN-266 | New credential namespace not rendered in admin console | [LRN-266](LRN-266-console-ui-missing-new-namespace.md) |
| LRN-267 | CHANGELOG labels runtime wave as docs-only | [LRN-267](LRN-267-changelog-misses-runtime-changes.md) |
| LRN-268 | Plan-time component ID goes stale in Reuses | [LRN-268](LRN-268-stale-component-id-reuses.md) |
| LRN-269 | Secret-leak test checks values code never saw | [LRN-269](LRN-269-vacuous-secret-leak-test.md) |
| LRN-270 | Unchanged-behavior test skips listed probes | [LRN-270](LRN-270-unchanged-probe-test-incomplete.md) |
| LRN-271 | Template mirror edited but never committed or pushed | [LRN-271](LRN-271-template-mirror-unpropagated.md) |
| LRN-272 | New consent path skips client-lifecycle side effects | [LRN-272](LRN-272-consent-path-lifecycle-parity.md) |
| LRN-273 | Template mirror gap persists across redteam rounds | [LRN-273](LRN-273-template-mirror-still-open.md) |
| LRN-274 | Widened actor invalidates capacity-bound assumptions | [LRN-274](LRN-274-widened-actor-capacity-bound.md) |
| LRN-275 | Test imports dependency missing from gate extra | [LRN-275](LRN-275-test-dep-not-in-gate-extra.md) |
| LRN-276 | Template mirror edits left uncommitted in peer repo | [LRN-276](LRN-276-template-mirror-unpropagated.md) |
| LRN-277 | Redteam fix to shared store not gated on feature flag | [LRN-277](LRN-277-fix-not-gated-on-flag.md) |
| LRN-278 | Passing in-repo parity test mistaken for template propagation | [LRN-278](LRN-278-parity-test-not-propagation.md) |
| LRN-279 | Dirty template tree blocks whole-file staging of wave hunks | [LRN-279](LRN-279-dirty-template-hunk-staging.md) |
| LRN-280 | Weaker approver writes trust flag read by stronger path | [LRN-280](LRN-280-weak-approver-shared-trust-flag.md) |
| LRN-281 | New exemption flag leaves pre-upgrade records evictable | [LRN-281](LRN-281-unmigrated-exemption-flag-eviction.md) |
| LRN-282 | Forwarded-for parser trusts attacker-chosen leftmost hop | [LRN-282](LRN-282-xff-leftmost-hop-spoof.md) |
| LRN-283 | Name imported and redefined locally breaks mypy gate | [LRN-283](LRN-283-import-local-redef-mypy.md) |
| LRN-284 | Per-source quota ties evict oldest and ignore IPv6 prefix | [LRN-284](LRN-284-quota-tie-evicts-oldest.md) |
| LRN-285 | Evicting heaviest source still lets one source evict another | [LRN-285](LRN-285-heaviest-source-eviction-unfair.md) |
| LRN-286 | Client-IP key wiring lacks route-level test | [LRN-286](LRN-286-ip-key-route-wiring-untested.md) |
| LRN-287 | Todo "Reuses: C-NNN" either/or directive landed neither branch | [LRN-287](LRN-287-registry-reuse-directive-unmet.md) |
| LRN-288 | Docs and ADR describe eviction/refusal policy the code no longer has | [LRN-288](LRN-288-stale-policy-docs.md) |
| LRN-289 | IdP sign-in admits any user of a non-Entra issuer with no role/group | [LRN-289](LRN-289-idp-admission-fail-open.md) |
| LRN-290 | Todo done while template peer-repo edit is uncommitted | [LRN-290](LRN-290-peer-repo-unpushed-edit.md) |
| LRN-291 | Pinned-tenant check misses multi-user tenant GUIDs | [LRN-291](LRN-291-pinned-tenant-guid-bypass.md) |
| LRN-292 | SI-2 annotation names a no-leak test that was never written | [LRN-292](LRN-292-annotated-leak-test-missing.md) |
| LRN-293 | New field on exported class lacks scope, changelog, durability note | [LRN-293](LRN-293-public-field-undocumented.md) |
| LRN-294 | Spend cap on extra model call ignores its input tokens | [LRN-294](LRN-294-extra-call-input-tokens.md) |
| LRN-295 | New model call on exit path skips budget and deadline guards | [LRN-295](LRN-295-new-call-skips-guards.md) |
| LRN-296 | Bare catch-all on model call hides seam contract breaks | [LRN-296](LRN-296-silent-catchall-seam.md) |
| LRN-297 | Cap check charging input re-send makes budget summary dead code | [LRN-297](LRN-297-cap-check-dead-path.md) |
| LRN-298 | Output-only token cap does not bound total call spend | [LRN-298](LRN-298-output-only-cap-spend.md) |
| LRN-299 | Feature never fires under default policy values | [LRN-299](LRN-299-default-policy-untested.md) |
| LRN-300 | Loop event field change is public surface, list in todo and CHANGELOG | [LRN-300](LRN-300-event-shape-public-surface.md) |
| LRN-301 | New bridge_trailing_user caller must amend LRN-144 call-site list | [LRN-301](LRN-301-pinned-callsite-amend.md) |
| LRN-302 | Wave must not redefine a cost limit from an AC without a ruling | [LRN-302](LRN-302-wave-changes-cost-ac.md) |
| LRN-303 | Output caps on reasoning models must leave room for reasoning | [LRN-303](LRN-303-reasoning-model-output-cap.md) |
| LRN-304 | Cap formulas must be tested at default policy and settings | [LRN-304](LRN-304-untested-default-policy-branch.md) |
| LRN-305 | Model client must not add unconfigured provider parameters | [LRN-305](LRN-305-unconfigured-provider-param.md) |
| LRN-306 | Spend-cap promises must count input re-send tokens | [LRN-306](LRN-306-output-only-spend-cap.md) |
| LRN-307 | Wave narrowed a cost-guard AC from total spend to output-only | [LRN-307](LRN-307-cost-guard-ac-narrowed.md) |
| LRN-308 | Debug-round fix silently narrowed a maintainer-ruled behavior | [LRN-308](LRN-308-ruling-narrowed-by-debug.md) |
| LRN-309 | Small token cap on a reasoning model returns empty output | [LRN-309](LRN-309-reasoning-model-small-cap.md) |
| LRN-310 | Default-on ZoneInfo use without tzdata breaks boot | [LRN-310](LRN-310-zoneinfo-needs-tzdata.md) |
| LRN-311 | Provider-specific cap widening exceeds model limits, unratified | [LRN-311](LRN-311-provider-cap-widening-unratified.md) |
| LRN-312 | Cell sanitizer used on identifiers corrupts copy-back ids | [LRN-312](LRN-312-id-sanitizer-mangles-ids.md) |
| LRN-313 | Reversed conformance rule left in other skill phrasings | [LRN-313](LRN-313-reversed-rule-stale-phrasing.md) |
| LRN-314 | Harness skill edit missing template mirror | [LRN-314](LRN-314-template-skill-mirror-stale.md) |
| LRN-315 | New untrusted value needs sanitization test per renderer | [LRN-315](LRN-315-per-site-sanitize-tests.md) |
| LRN-316 | AG-UI input rejection must not scan replayed history | [LRN-316](LRN-316-agui-reject-history-bricks.md) |
| LRN-317 | Client enum-like string echoed unbounded into wire error text | [LRN-317](LRN-317-client-string-echoed-in-error.md) |
| LRN-318 | Validation skip-guard looser than the branch it defers to | [LRN-318](LRN-318-validation-skip-guard-mismatch.md) |
| LRN-319 | Fix silently narrows a maintainer ruling | [LRN-319](LRN-319-fix-narrows-ruling-silently.md) |
| LRN-320 | SI annotation satisfied by docs warning only | [LRN-320](LRN-320-si-annotation-unmet-docs-only.md) |
| LRN-321 | Wire break filed under Fixed, not Breaking changes | [LRN-321](LRN-321-wire-break-not-in-breaking.md) |
| LRN-322 | Production files changed outside todo scope and CHANGELOG | [LRN-322](LRN-322-undeclared-wave-scope.md) |
| LRN-323 | Wave narrows maintainer ruling without checkable approval | [LRN-323](LRN-323-unratified-ruling-narrowing.md) |
| LRN-324 | Identical-copies AC checked by grep, not whole-file diff | [LRN-324](LRN-324-skill-mirror-drift.md) |
| LRN-325 | Mirror guard test silently passes when peer repo absent | [LRN-325](LRN-325-silent-skip-mirror-test.md) |
| LRN-326 | Registry meta-test vacuous for unset sample fields | [LRN-326](LRN-326-vacuous-sample-meta-test.md) |
| LRN-327 | Per-model AC tested on only a sample of models for second surface | [LRN-327](LRN-327-ac-surface-coverage-gap.md) |
| LRN-328 | Content-type allowlist skips non-list payload shapes | [LRN-328](LRN-328-allowlist-all-payload-shapes.md) |
| LRN-329 | Wave group closed with failing AC tests (source change lost) | [LRN-329](LRN-329-group-ac-tests-unverified.md) |
| LRN-330 | Superseded exemption test not inverted with ruling | [LRN-330](LRN-330-superseded-test-not-inverted.md) |
| LRN-331 | Git stash/reset in shared wave tree wipes other groups | [LRN-331](LRN-331-wave-git-stash-wipes-work.md) |
| LRN-332 | Template mirror pushed while SDK-side change was lost | [LRN-332](LRN-332-mirror-push-without-sdk-diff.md) |
| LRN-333 | Deterministic cross-check diverges from AI parse rules | [LRN-333](LRN-333-scan-ai-rule-mismatch.md) |
| LRN-334 | Standalone text slot can forge a sibling row | [LRN-334](LRN-334-standalone-slot-sibling-forgery.md) |
| LRN-335 | Byte-identical local mirror is not delivery to template | [LRN-335](LRN-335-template-mirror-not-delivered.md) |
| LRN-336 | Untrusted line in id-bearing list can forge a row | [LRN-336](LRN-336-untrusted-preview-row-forgery.md) |
| LRN-337 | New cap setting needs a route-level wiring test | [LRN-337](LRN-337-setting-wiring-route-test.md) |
| LRN-338 | Directory in todo scope declares no files | [LRN-338](LRN-338-directory-scope-declares-nothing.md) |
| LRN-339 | Untrusted slot keeps ':' and forges a sibling id line | [LRN-339](LRN-339-label-line-forges-id.md) |
| LRN-340 | SI-2 annotation landed without its named no-leak test | [LRN-340](LRN-340-si2-annotation-missing-test.md) |
| LRN-341 | Failed LRN Check keeps severity; MCP catch-all still logs exception | [LRN-341](LRN-341-failed-check-keeps-severity.md) |
| LRN-342 | Wave narrowed a maintainer ruling and docs claimed otherwise | [LRN-342](LRN-342-unratified-ruling-narrowing.md) |
| LRN-343 | Ruling condition not mapped to real runtime switch | [LRN-343](LRN-343-ruling-gate-vs-runtime-switch.md) |
| LRN-344 | Reuses directives treated as optional, not acceptance criteria | [LRN-344](LRN-344-reuses-directive-unchecked.md) |
| LRN-345 | Scope scan accepts only backticked paths, misses planner format | [LRN-345](LRN-345-scope-scan-format-mismatch.md) |
| LRN-346 | Maintainer ruling implemented for fewer slots than named | [LRN-346](LRN-346-ruling-narrowed-unratified.md) |
| LRN-347 | Mirror byte-identity test compares local tree, not pushed commit | [LRN-347](LRN-347-mirror-check-local-tree.md) |
| LRN-348 | Extra security swap added beyond ruling's only-X wording | [LRN-348](LRN-348-extra-swap-beyond-ruling.md) |
| LRN-349 | Narrowing Optional field to non-None default rejects explicit null | [LRN-349](LRN-349-narrowed-field-explicit-null.md) |
| LRN-350 | Reuses directive ignored, second test parser written | [LRN-350](LRN-350-reuse-directive-second-parser.md) |
| LRN-351 | Test inspects raw strings instead of calling shared parser verdict | [LRN-351](LRN-351-test-skips-shared-parser.md) |
| LRN-352 | Validator message formats the rejected value despite hide_input_in_errors | [LRN-352](LRN-352-validator-message-echoes-value.md) |
| LRN-353 | Non-finite coercion misses nullable int fields and runs too late | [LRN-353](LRN-353-nullable-int-nonfinite-coercion.md) |
| LRN-354 | Wire validity enforced only in validators, not at serialization | [LRN-354](LRN-354-wire-guard-at-serialization.md) |
| LRN-355 | Wave kept legacy behaviour that conflicts with new maintainer ruling | [LRN-355](LRN-355-ruling-vs-legacy-field-behaviour.md) |
| LRN-356 | Base-class validator is a breaking change for downstream models | [LRN-356](LRN-356-base-class-validator-breaking-changelog.md) |
| LRN-357 | Breaking CHANGELOG entries must cite their authority | [LRN-357](LRN-357-breaking-entry-needs-authority.md) |
| LRN-358 | Strict serializer kills AG-UI stream on raw client JSON | [LRN-358](LRN-358-strict-serializer-agui-ingress.md) |
| LRN-359 | Shared serializer edits must be declared in todo scope | [LRN-359](LRN-359-shared-serializer-todo-scope.md) |
| LRN-360 | Reject non-finite JSON at every protocol ingress | [LRN-360](LRN-360-nonfinite-ingress-all-surfaces.md) |
| LRN-361 | Mid-wave ingress hardening missing from todo Modifies and CHANGELOG | [LRN-361](LRN-361-midwave-scope-drift.md) |
| LRN-362 | Strict JSON parser misses overflowing floats (1e999) | [LRN-362](LRN-362-strict-json-overflow-floats.md) |
| LRN-363 | Stricter SSE serializer needs terminal-frame guard in every generator | [LRN-363](LRN-363-strict-serializer-sse-guard.md) |
| LRN-364 | MCP writer lacks non-finite output guard after strict serializer | [LRN-364](LRN-364-mcp-nonfinite-output-guard.md) |
| LRN-365 | Todo AC requiring a CHANGELOG entry shipped without one | [LRN-365](LRN-365-changelog-entry-missing.md) |
| LRN-366 | New sanitizer bypasses canonical cut-and-marker helper | [LRN-366](LRN-366-sanitizer-truncation-divergence.md) |
| LRN-367 | Release gate lacks per-issue CHANGELOG coverage check | [LRN-367](LRN-367-release-gate-changelog-coverage.md) |
| LRN-368 | Sanitizer defines its own look-alike table | [LRN-368](LRN-368-duplicate-lookalike-table.md) |
| LRN-369 | SI note lands without a hostile-input test | [LRN-369](LRN-369-si-note-without-hostile-test.md) |
| LRN-370 | Validation-order AC half-implemented; old tests pin old order | [LRN-370](LRN-370-validation-reorder-half-done.md) |
| LRN-371 | Wire key removal and wire() type change filed outside Breaking | [LRN-371](LRN-371-wire-break-outside-breaking.md) |
| LRN-372 | Text fallback alias order differs from wire serializer | [LRN-372](LRN-372-text-wire-alias-order-mismatch.md) |
| LRN-373 | Test named for a field never asserts it; text drops wire field | [LRN-373](LRN-373-test-name-overclaims-field.md) |
| LRN-374 | Shared wire() return-type change breaks AG-UI schema and metadata | [LRN-374](LRN-374-wire-return-type-transport-split.md) |
| LRN-375 | Return-type change leaves caller files off the todo Modifies line | [LRN-375](LRN-375-callers-missing-from-modifies.md) |
| LRN-376 | Green pytest does not prove mypy gate passes after route change | [LRN-376](LRN-376-mypy-gate-after-route-change.md) |
| LRN-377 | Model wire() fix silently changes protocol frame shape | [LRN-377](LRN-377-wire-override-breaks-frame.md) |
| LRN-378 | Removed base-class opt-out flag must be Breaking and fail loud | [LRN-378](LRN-378-removed-optout-flag-silent.md) |
| LRN-379 | Wave CHANGELOG omits changed files and new public symbols | [LRN-379](LRN-379-changelog-names-files-symbols.md) |
| LRN-380 | SI AC naming "every route" needs a test per route | [LRN-380](LRN-380-every-route-needs-test.md) |
| LRN-381 | Reuses directive means the named shared helper, not a private one | [LRN-381](LRN-381-reuses-directive-shared-helper.md) |
| LRN-382 | Removal guard must catch the documented declaration form | [LRN-382](LRN-382-removal-guard-declaration-form.md) |
| LRN-383 | Reuses-driven helper still needs scope and CHANGELOG entry | [LRN-383](LRN-383-reuses-helper-scope-declaration.md) |
| LRN-384 | Breaking CHANGELOG bullet and fail-loud guard need a ruling | [LRN-384](LRN-384-breaking-change-needs-ruling.md) |
| LRN-385 | Gate semantics change left old-ruling tests red | [LRN-385](LRN-385-stale-tests-after-gate-change.md) |
| LRN-386 | Remote card values copied into requests without caps or fixed source | [LRN-386](LRN-386-untrusted-remote-value-caps.md) |
| LRN-387 | Existing LRN Check clause contradicts a landed fix | [LRN-387](LRN-387-stale-lrn-check-vs-fix.md) |
| LRN-388 | Raw user value logged despite Reuses component | [LRN-388](LRN-388-reuse-component-skipped-log.md) |
| LRN-389 | SI-2 no-leak test covered only one named path | [LRN-389](LRN-389-si2-per-path-caplog-tests.md) |
| LRN-390 | New key kind inherits operator power via kind check | [LRN-390](LRN-390-new-key-kind-inherits-admin-power.md) |
| LRN-391 | SI-5 listed surfaces left without tests | [LRN-391](LRN-391-si5-surface-each-needs-test.md) |
| LRN-392 | Skill credential switch left stale admin placeholders | [LRN-392](LRN-392-stale-credential-placeholder-skill.md) |
| LRN-393 | Teardown step placed before later loop rounds | [LRN-393](LRN-393-teardown-inside-loop.md) |
| LRN-394 | Authz narrowing missing changelog, docs and per-kind tests | [LRN-394](LRN-394-silent-authz-narrowing.md) |
| LRN-395 | Mirrored SKILL.md copies diverge on security rules | [LRN-395](LRN-395-mirrored-skill-divergence.md) |
| LRN-396 | New field inserted mid-dataclass shifts positional args | [LRN-396](LRN-396-dataclass-field-order.md) |
| LRN-397 | Hardening beyond ruled scope shipped without ruling | [LRN-397](LRN-397-unruled-breaking-hardening.md) |
| LRN-398 | Template skill edits left uncommitted in peer repo | [LRN-398](LRN-398-peer-repo-uncommitted-edits.md) |
| LRN-399 | Cleanup step deletes the only copy of a secret | [LRN-399](LRN-399-cleanup-destroys-sole-copy.md) |
| LRN-400 | SI annotation marked done with call sites left | [LRN-400](LRN-400-incomplete-si-annotation-coverage.md) |
| LRN-401 | Skill says load secret without showing how | [LRN-401](LRN-401-secret-load-command-missing.md) |
| LRN-402 | Fixing one secret-printing step, sibling left leaking | [LRN-402](LRN-402-sibling-mint-step-unfixed.md) |
| LRN-403 | Test fixture hand-copies the banner it parses | [LRN-403](LRN-403-handwritten-banner-fixture.md) |
| LRN-404 | Secret temp file path built from placeholder or guessable name | [LRN-404](LRN-404-secret-tempfile-placeholder-path.md) |
| LRN-405 | Whole-file skill sync to template wipes per-repo lines | [LRN-405](LRN-405-whole-file-mirror-overwrite.md) |
| LRN-406 | Mirror guard skips or checks only a fragment | [LRN-406](LRN-406-partial-mirror-guard-skips.md) |
| LRN-407 | CHANGELOG needs one entry per GH item and new public symbols | [LRN-407](LRN-407-changelog-per-gh-entry.md) |
| LRN-408 | ContextVar bound around hand-off to a running worker is a no-op | [LRN-408](LRN-408-contextvar-bind-after-worker.md) |
| LRN-409 | Template skill mirror edited but not committed in peer repo | [LRN-409](LRN-409-template-mirror-uncommitted.md) |
| LRN-410 | Annotated tests missing and leak checks run outside the app | [LRN-410](LRN-410-annotated-test-missing-leak.md) |
| LRN-411 | Per-request state passed to worker via shared record field races | [LRN-411](LRN-411-resume-identity-race.md) |
| LRN-412 | Handoff state on TaskRecord lost by copy-on-get stores | [LRN-412](LRN-412-store-copy-handoff-state.md) |
| LRN-413 | File listed under Reads was modified, missing from scope and changelog | [LRN-413](LRN-413-read-only-file-changed.md) |
| LRN-414 | Wave deviated from maintainer ruling without ratification | [LRN-414](LRN-414-unratified-ruling-deviation.md) |
| LRN-415 | JS block replaced by text edit left file unparseable | [LRN-415](LRN-415-js-edit-must-parse.md) |
| LRN-416 | Substring asserts on JS source are not a gate | [LRN-416](LRN-416-substring-tests-miss-syntax.md) |
| LRN-417 | Todo signed off without its CHANGELOG entries | [LRN-417](LRN-417-changelog-ac-skipped.md) |
| LRN-418 | Resume tests must assert the handler's result | [LRN-418](LRN-418-resume-test-checks-result.md) |
| LRN-419 | Parallel groups each skipped CHANGELOG entries | [LRN-419](LRN-419-parallel-groups-skip-changelog.md) |
| LRN-420 | Unknown-key allowlist must match what model_validate accepts | [LRN-420](LRN-420-allowlist-must-match-validator.md) |
| LRN-421 | New bridge_trailing_user caller needs LRN-144 Check amended | [LRN-421](LRN-421-new-bridge-caller-amend-lrn.md) |
| LRN-422 | Reused helper prompt text states false premise for new trigger | [LRN-422](LRN-422-reused-prompt-false-premise.md) |
| LRN-423 | CHANGELOG missing Added entries and incomplete file lists | [LRN-423](LRN-423-changelog-added-and-file-lists.md) |
| LRN-424 | Todo-required CHANGELOG entry lost in shared file | [LRN-424](LRN-424-todo-changelog-entry-lost.md) |
| LRN-425 | DESIGN.md left stale after protocol behaviour change | [LRN-425](LRN-425-design-spec-stale-after-behavior-change.md) |
| LRN-426 | Ruling reversal must sweep every doc, not only the named one | [LRN-426](LRN-426-ruling-reversal-doc-sweep.md) |
| LRN-427 | Substring doc test can lock in a reversed rule | [LRN-427](LRN-427-doc-test-locks-old-rule.md) |
| LRN-428 | Per-key quota must evict own entries before insert | [LRN-428](LRN-428-quota-evict-before-insert.md) |
| LRN-429 | Thread offload removes free atomicity of read-modify-write | [LRN-429](LRN-429-thread-offload-lost-atomicity.md) |
| LRN-430 | Check-then-delete safety rules need a lock off the event loop | [LRN-430](LRN-430-check-then-delete-needs-lock.md) |
| LRN-431 | Not-blocked-loop test must make only the code under test slow | [LRN-431](LRN-431-unproven-loop-block-test.md) |
| LRN-432 | Process-wide lock across store I/O starves the to_thread pool | [LRN-432](LRN-432-global-lock-starves-pool.md) |
| LRN-433 | CHANGELOG must name every changed file and new public method | [LRN-433](LRN-433-changelog-names-every-file.md) |
| LRN-434 | Fix-round test files and base-class changes missing from todo scope | [LRN-434](LRN-434-fix-round-test-files-unlisted.md) |
| LRN-435 | CHANGELOG [Unreleased] missing entries for GH ids a group names in its AC | [LRN-435](LRN-435-changelog-entry-per-gh-id.md) |
| LRN-436 | Breaking CHANGELOG bullet cites no spec clause or ruling URL | [LRN-436](LRN-436-breaking-entry-needs-citation.md) |
| LRN-437 | Todo lists CHANGELOG.md in Creates but lands no line | [LRN-437](LRN-437-creates-changelog-unfulfilled.md) |
| LRN-438 | New LoopEvent dataclass field inserted before existing fields | [LRN-438](LRN-438-event-field-inserted-midclass.md) |
| LRN-439 | Disconnect-cancel hook skips the resume branch | [LRN-439](LRN-439-disconnect-cancel-misses-resume.md) |
| LRN-440 | Every GH item needs its own CHANGELOG bullet, even additive card fields | [LRN-440](LRN-440-changelog-entry-per-gh-item.md) |
| LRN-441 | Test file relaxed for a wire change must be declared in the todo | [LRN-441](LRN-441-relaxed-test-file-undeclared.md) |
| LRN-442 | Verify where a foreign protocol field sits in its published schema | [LRN-442](LRN-442-foreign-protocol-field-location.md) |
| LRN-443 | CHANGELOG Changed list must come from git diff, not headline fix | [LRN-443](LRN-443-changelog-changed-list-from-diff.md) |
| LRN-444 | Breaking CHANGELOG bullet admitting no ruling URL blocks the wave | [LRN-444](LRN-444-breaking-bullet-needs-ruling-url.md) |
| LRN-445 | Shared CHANGELOG hides a missing sibling GH entry | [LRN-445](LRN-445-shared-changelog-missing-sibling.md) |
| LRN-446 | Split-out helper module missing from todo scope and CHANGELOG | [LRN-446](LRN-446-helper-module-unlisted.md) |
| LRN-447 | JSON-Pointer setter lacks prototype-pollution guard | [LRN-447](LRN-447-jsonpointer-proto-pollution.md) |
| LRN-448 | Deliverable gate classifies files by name substring | [LRN-448](LRN-448-gate-filename-substring-match.md) |
| LRN-449 | Deliverable gate treats NNN placeholder paths as files | [LRN-449](LRN-449-gate-placeholder-paths-concrete.md) |
| LRN-450 | Time-based workflow gate reads banned clock and fails open | [LRN-450](LRN-450-workflow-clock-gate-fails-open.md) |
| LRN-451 | Stale-quote filter drops findings whose quote was never present | [LRN-451](LRN-451-stale-filter-drops-unseen-quotes.md) |
| LRN-452 | Mirror-pushed test keyed to upstream hides undelivered mirror | [LRN-452](LRN-452-mirror-test-keyed-to-upstream.md) |
| LRN-453 | Gate inputs re-read from model-relayed text are not deterministic | [LRN-453](LRN-453-gate-inputs-relayed-by-model.md) |
| LRN-454 | Rate-limited scenarios scored as pass in acceptance gate | [LRN-454](LRN-454-excluded-failure-counted-as-pass.md) |
| LRN-455 | Redteam findings must quote the current line so stale ones can be dropped | [LRN-455](LRN-455-stale-redteam-findings.md) |
| LRN-456 | Documented tool-schema pattern not checked against model providers | [LRN-456](LRN-456-unsafe-schema-doc-recipe.md) |
| LRN-457 | Docstring-only edit to a Reads-only file left undeclared | [LRN-457](LRN-457-docstring-edit-undeclared.md) |
| LRN-458 | Re-captured golden hash test not declared in todo | [LRN-458](LRN-458-golden-hash-test-undeclared.md) |
| LRN-459 | Auto-filing with gh --label fails when labels do not exist | [LRN-459](LRN-459-gh-issue-missing-label.md) |
| LRN-460 | Runner copy repeats missing-label auto-filing defect | [LRN-460](LRN-460-runner-copy-missing-label.md) |
| LRN-461 | Public-output redaction tested only on AC sample secrets | [LRN-461](LRN-461-redaction-untested-secret-formats.md) |
| LRN-462 | Redaction fix must be mirrored across both wave runners | [LRN-462](LRN-462-runner-mirror-redaction-parity.md) |
| LRN-463 | Redteam finding ids are not unique across rounds | [LRN-463](LRN-463-finding-id-join-collision.md) |
| LRN-464 | Finding-id join defect repeated in sdk-wave.js | [LRN-464](LRN-464-sdk-wave-id-join-parity.md) |
| LRN-465 | CHANGELOG template SHA taken before final fix round | [LRN-465](LRN-465-changelog-template-sha-stale.md) |
| LRN-466 | Wave docs contradict maintainer ruling without re-ruling | [LRN-466](LRN-466-ruling-contradicted-by-docs.md) |
| LRN-467 | CHANGELOG alias mention trips ratchet test unplanned | [LRN-467](LRN-467-changelog-alias-ratchet-test.md) |
| LRN-468 | Loop event not reshaped with the A2A artifact frame | [LRN-468](LRN-468-loop-event-diverges-from-frame.md) |
| LRN-469 | MCP tools/call ignores advertised outputSchema on type mismatch | [LRN-469](LRN-469-mcp-output-schema-unenforced.md) |
| LRN-470 | Unknown pydantic error type code echoed into tool error text | [LRN-470](LRN-470-pydantic-type-code-echo.md) |
| LRN-471 | New public API filed under Changed; files not named | [LRN-471](LRN-471-changelog-added-vs-changed.md) |
| LRN-472 | New boot-time rejection shipped without Breaking entry | [LRN-472](LRN-472-boot-rejection-is-breaking.md) |
| LRN-473 | Unreleased work added to tagged release section | [LRN-473](LRN-473-tagged-changelog-section-edit.md) |
| LRN-474 | Strict schema drops required but validator still demands it | [LRN-474](LRN-474-schema-loosening-vs-validator.md) |
| LRN-475 | Null collapse must apply only at property positions | [LRN-475](LRN-475-nullable-collapse-nested-positions.md) |
| LRN-476 | Null collapse breaks types whose serializer re-inserts null | [LRN-476](LRN-476-nullable-collapse-serializer-reinsert.md) |
| LRN-477 | Strict outputSchema must match exclude_none serialization | [LRN-477](LRN-477-outputschema-exclude-none-mismatch.md) |
| LRN-478 | caplog no-leak asserts empty after first build_app | [LRN-478](LRN-478-caplog-propagation-first-build.md) |
| LRN-479 | Unfixed caplog empty-capture in GH-205 skill leak tests | [LRN-479](LRN-479-caplog-empty-capture-unfixed.md) |
| LRN-480 | Allowlist narrower than the ruling that created it | [LRN-480](LRN-480-allowlist-narrower-than-ruling.md) |
| LRN-481 | Root caplog misses agent_sdk logger after build_app | [LRN-481](LRN-481-root-caplog-misses-sdk-logger.md) |
| LRN-482 | Strict schema decides nullability before $ref resolution | [LRN-482](LRN-482-nullability-before-ref-resolution.md) |
| LRN-490 | Parallel groups each open their own Unreleased heading | [LRN-490](LRN-490-parallel-groups-duplicate-unreleased.md) |
| LRN-491 | CHANGELOG Unreleased bullet must name every changed agent_sdk file | [LRN-491](LRN-491-changelog-names-all-changed-files.md) |
| LRN-492 | Failed-request rollback must restore UI, not just state | [LRN-492](LRN-492-restore-ui-with-state.md) |
