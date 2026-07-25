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
| LRN-014 | `pytest -q tests/` bypasses `addopts` ignore exclusions — always use bare `pytest -q` | [LRN-014](LRN-014-pytest-explicit-path-bypasses-addopts.md) |
| LRN-015 | MCP tools/call — coercion failure must return isError:True, never except:pass | [LRN-015](LRN-015-mcp-coercion-failure-must-return-iserror.md) |
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
| LRN-043 | MCP tier-1 tools missing openWorldHint annotation causes client over-restriction | [LRN-043](LRN-043-mcp-tier1-tools-openworldhint-missing.md) |
| LRN-044 | ValidationError swallowed by catch-all loop — SI-2 requires explicit enrichment | [LRN-044](LRN-044-validationerror-swallowed-in-catch-all.md) |
| LRN-045 | JSON parse failure must return -32700, not -32602 (invalid-params) | [LRN-045](LRN-045-json-parse-error-wrong-jsonrpc-code.md) |
| LRN-046 | A2UI DataPart emitted unconditionally — requires X-A2A-Extensions opt-in gate | [LRN-046](LRN-046-a2ui-datapart-emitted-without-extension-optin.md) |
| LRN-047 | Terminal re-message rule violated — _continue_from_terminal creates new task instead of returning error | [LRN-047](LRN-047-terminal-re-message-creates-task-instead-of-error.md) |
| LRN-048 | Inbound Message mutated with server-assigned taskId/contextId before archiving in history | [LRN-048](LRN-048-inbound-message-contextid-mutation-in-history.md) |
| LRN-049 | AG-UI CUSTOM events wrongly gated on catalog membership — must emit freely | [LRN-049](LRN-049-agui-custom-emit-freely-catalog-gate-wrong.md) |
| LRN-050 | CLAUDE.md/gitignore consistency gap — credential globs missing from .gitignore | [LRN-050](LRN-050-claudemd-gitignore-consistency-gap.md) |
| LRN-051 | uv --no-dev is a silent no-op on extras-only ([project.optional-dependencies]) layouts | [LRN-051](LRN-051-uv-no-dev-silent-noop-on-extras-only-layouts.md) |
| LRN-052 | Gitignored/untracked path cannot land in a wave todo — verify with git ls-files at plan time | [LRN-052](LRN-052-gitignored-path-cannot-land-in-wave-todo.md) |
| LRN-053 | Wave scope must union Creates: AND Modifies: paths — Creates-only derivation silently bypasses modify-only waves | [LRN-053](LRN-053-wave-scope-must-union-creates-and-modifies.md) |
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
| LRN-068 | Phase redteam scores ACs against unimplemented wave targets (empty diff false-pass) | [LRN-068](LRN-068-phase-redteam-empty-diff-false-pass.md) |
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
| LRN-101 | Agent card description field must never fall back to empty string — use display_name sentinel instead | [LRN-101](LRN-101-agent-card-description-empty-string-fallback.md) |
| LRN-102 | TOOL_PROGRESS CUSTOM event emitted in ag_ui.py but absent from CUSTOM_EVENTS tuple, card schema, DESIGN.md §5.3 table, and console router — parity guard silent because both sides missing | [LRN-102](LRN-102-tool-progress-custom-event-parity-gap.md) |
| LRN-103 | A2A multi-turn continuation must use contextId, not taskId, for completed tasks | [LRN-103](LRN-103-a2a-multiturn-contextid-continuation.md) |
| LRN-104 | Deferred imports in model clients must not be silently caught by bare except Exception | [LRN-104](LRN-104-deferred-import-silent-wrap.md) |
| LRN-105 | Bare "except Exception" in model client invoke paths swallows distinct error categories (e.g. RateLimitError) as generic UPSTREAM | [LRN-105](LRN-105-broad-except-swallows-error-category.md) |
| LRN-106 | caplog assertions on agent_sdk.* loggers false-green outside full-suite order | [LRN-106](LRN-106-caplog-propagate-false-order-dependent.md) |
| LRN-107 | Fixed broken test idiom recurs uncaught in a sibling test | [LRN-107](LRN-107-duplicated-broken-test-idiom.md) |
| LRN-108 | Unautomated documentation anchors drift silently | [LRN-108](LRN-108-unautomated-doc-anchor-drift.md) |
| LRN-109 | Documented ledger-append fix (LRN-062) recurred unenforced in w029 | [LRN-109](LRN-109-wave-ledger-guard-not-enforced.md) |
| LRN-110 | Required-but-nullable field silently dropped by blanket exclude_none | [LRN-110](LRN-110-required-nullable-field-dropped-by-exclude-none.md) |
| LRN-111 | AG-UI Interrupt.expiresAt wire format — ISO-8601 citation and verification method | [LRN-111](LRN-111-agui-interrupt-expires-at-wire-format-citation.md) |
| LRN-112 | Monotonic clock value fed to datetime.fromtimestamp() as if it were epoch time | [LRN-112](LRN-112-monotonic-clock-epoch-confusion.md) |
| LRN-113 | New abstractmethod on public ABC breaks external subclasses | [LRN-113](LRN-113-public-abc-new-abstractmethod.md) |
| LRN-114 | Non-total content extraction crashes AG-UI SSE stream without terminal frame | [LRN-114](LRN-114-non-total-sse-validation-crash.md) |
| LRN-115 | AG-UI _capabilities() fail-closed tier="none" default is intentional — do not align to spec tier="core" | [LRN-115](LRN-115-agui-capabilities-fail-closed-tier-none-default.md) |
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
| LRN-134 | A2UI-over-A2A DataPart "messages" wrapper key satisfies A2A v0.3.0 but contradicts A2UI v0.9.1's own literal binding | [LRN-134](LRN-134-a2ui-a2a-datapart-messages-key-not-spec-mandated.md) |
| LRN-135 | Portable a2ui-advisor oracle rewritten to teach this SDK's private `data.messages` deviation as the canonical A2UI-over-A2A rule, burying the spec's bare-array binding | [LRN-135](LRN-135-portable-oracle-encodes-deviation.md) |
