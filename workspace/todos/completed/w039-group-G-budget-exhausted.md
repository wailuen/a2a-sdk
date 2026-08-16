wave: w039
group: G
date: 2026-08-15
round_count: 5
status: resolved
resolved_date: 2026-08-16
open_findings: []
resolved_findings: [RT-001, RT-002, RT-003, RT-004, RT-005, RT-006, RT-007, RT-008, RT-009]
last_reconciled: 2026-08-16

## Resolution

RT-001 closed 2026-08-16: template/ (wailuen/a2a-agent-template) cloned into
this working tree, harness/workflows/wave-cycle.js copied over
template/.claude/workflows/wave-cycle.js (diff confirmed empty), committed
and pushed (wailuen/a2a-agent-template@de725dd). test_wave_cycle_is_harness_template_shared
and test_harness_and_template_copies_are_identical now PASS (no longer xfail)
in any checkout with template/ present. All nine findings in this file are
now resolved. This note is retained for history; it is NOT an open work item.
Do NOT re-run /wave w039 on account of this note.

## Findings

Each finding below carries a `resolution:` line, re-verified against the landed
working tree on 2026-08-15. LRN-100's archive relocation sweep only moves this
file out of `deferred/` once EVERY finding reads RESOLVED, so leaving them
unannotated made the sweep a permanent no-op and made a re-run of `/wave w039`
read nine open blockers where one exists. Re-verify and re-annotate as each
lands — do not bulk-close.

### RT-001
- **resolution: RESOLVED** — `template/` cloned; `template/.claude/workflows/wave-cycle.js`
  is byte-identical to `harness/workflows/wave-cycle.js` (verified via `diff`,
  exit 0); committed and pushed to wailuen/a2a-agent-template@de725dd.
  `test_wave_cycle_is_harness_template_shared` and
  `test_harness_and_template_copies_are_identical` both PASS.
- severity: high
- file: harness/workflows/wave-cycle.js
- description: The peer-repo runtime mirror template/.claude/workflows/wave-cycle.js — declared in both GH-131's and GH-132's Creates: with the LRN-071/LRN-085 annotation — never received either fix: template/ is absent from this checkout so the mandated `git -C template/ commit && git -C template/ push` step could not run, and the only local clone (/Users/wailuen/Development/a2a-sdk/template) is still 1670 lines with `const TODAY = args.today || new Date().toISOString().slice(0, 10)` at line 20 and no blockingFindings/AGENT_CALL_BUDGET/offendingUndeclaredScope, with a partial uncommitted edit that leaves it byte-divergent from both in-repo mirrors; test_workflow_sync.py's two propagation guards are XFAIL, not pass, and this is the copy downstream agents' /wave actually executes.
- fix: Clone wailuen/a2a-agent-template into template/ at the repo root, copy harness/workflows/wave-cycle.js over template/.claude/workflows/wave-cycle.js, confirm `diff` is empty, then `git -C template/ commit && git -C template/ push`; re-run pytest so test_wave_cycle_is_harness_template_shared and test_harness_and_template_copies_are_identical pass instead of xfailing.
- codify: A wave that declares a template/ deliverable must not be executed from a checkout where template/ is absent — the propagation step is unrunnable and every guard for it silently degrades to xfail.
- sdkCandidate: true

### RT-002
- **resolution: RESOLVED** — `.claude/workflows/wave-cycle.js:1374` writes
  `workspace/todos/deferred/<wave>-phase-budget-exhausted.md`, and
  `phaseBudgetBlocked` (declared line 776) feeds the archive block. Mirrored
  byte-identically in `harness/workflows/wave-cycle.js` (pinned by
  `tests/test_workflow_sync.py` axis 1).
- severity: high
- file: .claude/workflows/wave-cycle.js
- description: GH-132's severity floor narrowed `pRound >= 8` to mean only that critical/high findings survived 8 rounds, but that exit path still breaks with a bare log(): no deferred note is written (unlike the unit loop's -budget-exhausted.md), the break precedes `allHighFindings.push(...)` so the round's findings are never codified nor SDK-scanned, and protocolBlocked stays false so the wave archives — while phaseNonBlocking's medium/low findings DO get a durable -phase-medium-low.md, inverting durability against severity. Same defect in harness/workflows/wave-cycle.js:1123 and .claude/workflows/sdk-wave.js:1015; the returned `exhausted` flag is not branched on by either wave SKILL.md.
- fix: Before the `if (pRound >= 8) break`, push blocking.filter(f => f.codify) into allHighFindings, write workspace/todos/deferred/<wave>-phase-budget-exhausted.md with JSON.stringify(rt.findings, null, 2) mirroring the unit loop's defer call, and set a blocking flag so archive stops; land identically in all three runners and add a test_workflows.py case asserting the note write is reachable from the phase round-cap break.
- codify: When a loop-exit condition is narrowed to a severity floor, every surviving exit path now signals a strictly more severe state and must gain at least the durability (deferred note, codify capture, archive block) the pre-narrowing path had.
- sdkCandidate: true

### RT-003
- **resolution: RESOLVED** — `agent_sdk/contrib/commitments/executor.py:193`
  passes `frame_locations(exc)` in the generic branch; the surface is named in
  LRN-044's Check and covered by
  `tests/test_rt004_catchall_frame_parity.py::test_commitments_executor_catchall_logs_frame_locations`.
- severity: medium
- file: agent_sdk/contrib/commitments/executor.py
- description: The commitments executor's generic `except Exception` branch (line 175) logs only type(exc).__name__ and omits frame_locations(exc), breaking the C-012 four-surface parity its own adjacent comment asserts and the fixed contract LRN-044's rewritten Check codifies for the generic branch; this is the surface where diagnosability matters most (background fire, no caller observing the failure). LRN-044's Check grep also omits executor.py and tests/test_rt004_catchall_frame_parity.py covers only admin plus loop's three sites, so the gap is invisible to both the learning gate and the test suite.
- fix: Add `frames=%s` / frame_locations(exc) to the executor's generic-branch logger.error call, add agent_sdk/contrib/commitments/executor.py to LRN-044's Check grep, and add the fourth parity case to tests/test_rt004_catchall_frame_parity.py.
- sdkCandidate: true

### RT-004
- **resolution: RESOLVED** — `agent_sdk/app.py:63` defines
  `_is_azurite_emulator_connection_string()`; line 414 gates the DEV_MODE
  warning on `not _is_azurite_emulator_connection_string(conn_str)`.
- severity: medium
- file: agent_sdk/app.py
- description: The GH-129 DEV_MODE boot warning (line 406) fires for any non-None azure_storage_connection_string including `UseDevelopmentStorage=true`, then instructs the developer to 'use Azurite instead: set AZURE_STORAGE_CONNECTION_STRING=UseDevelopmentStorage=true' — the exact configuration already in effect. Every correctly-configured local run emits a warning claiming it may be writing real credentials into production, which is alert fatigue on the one control that exists because ~30 days of DEV_MODE runs minted 18,969 admin keys into prod; the sibling azure_storage_account_name branch has no equivalent false positive.
- fix: Skip the warning when the connection string is the emulator shortcut (starts with `UseDevelopmentStorage=true`, or contains `devstoreaccount1` / `127.0.0.1:10002`); add tests asserting no warning for the Azurite value and that the warning still fires for a real-shaped connection string.
- sdkCandidate: true

### RT-005
- **resolution: RESOLVED** — superseded and widened. The per-renderer opt-in this
  finding proposed was replaced by one whole-alphabet sanitiser applied to every
  cell; the alphabet and the sanitiser now live in the shared C-007 family as the
  public `agent_sdk.safe_cell_text` (`agent_sdk/common/redact.py`), with
  `content_types._sanitize_cell` a thin alias. `ContentModel`'s contract docstring,
  DESIGN.md's stable-core list and docs/content-types.md all name that helper.
  Locked from both directions by
  `tests/test_content_types.py::test_every_renderer_separator_is_neutralised` and
  `::test_untrusted_value_cannot_alter_render_structure`.
- severity: medium
- file: agent_sdk/models/content_types.py
- description: GH-130's delimiter-safety fix neutralises `|`/confusables and the full line-break set, but several to_plain_text() renderers join untrusted values on other structural delimiters that _sanitize_cell leaves intact. Verified against landed code: UserProfile(id='1', display_name='a> <ceo@corp.com', email='attacker@evil.com').to_plain_text() renders 'a> <ceo@corp.com <attacker@evil.com>', showing the reader (and the model, via runner.py tool-result folding, and the MCP wire via routes/mcp.py) two name<email> pairs with the first a fabricated identity. Same misrepresentation class as GH-130 on a delimiter set the documented contract (scoped to ' | ' and '\n' joins only) does not reach: UserProfile:860 and UserList:894 join on <>, DocumentList:930 on (), CalendarEvents:795 on ' @ ' and ' – '.
- fix: Neutralise or escape the structural characters each renderer actually joins on — at minimum '<' and '>' in UserProfile/UserList and '(' / ')' in DocumentList — and widen the delimiter-safety contract paragraph on ContentModel.to_plain_text beyond ' | ' and '\n' so future renderer authors are told the real rule; add a regression test per renderer.
- sdkCandidate: true

### RT-006
- **resolution: RESOLVED** — `workspace/components/README.md` carries `C-016
  safe_block_text` (line 20) and `C-017 frame_locations` (line 21) with full
  descriptions and call-site inventories.
- severity: medium
- file: agent_sdk/common/redact.py
- description: Two new cross-surface helpers landed unregistered in workspace/components/README.md: frame_locations (line 80), whose own docstring declares it 'Shared by every generic except Exception catch-all on a tool-dispatch surface (routes/mcp.py, routes/admin.py, agent/loop.py) so they stay at parity (LRN-044)' — a multi-surface parity contract that is already drifting (see RT-003) — and safe_block_text (line 56), the documented counterpart selector for markdown-contract fields. Only C-007 safe_error_text was updated to 'present'; neither new helper has a C-NNN row, so a future surface has no registry signal telling it to reuse rather than re-inline.
- fix: Add C-NNN registry rows and descriptions for safe_block_text and frame_locations in workspace/components/README.md, naming every current call site and, for frame_locations, the four-surface parity contract it enforces.
- sdkCandidate: false

### RT-007
- **resolution: RESOLVED** — `.claude/workflows/wave-cycle.js:1857` writes
  `workspace/todos/deferred/<wave>-lrn-cap-exceeded.md` under the
  `defer:codify:lrn-cap-exceeded` label.
- severity: medium
- file: .claude/workflows/wave-cycle.js
- description: The GH-132 MAX_LRN_PER_WAVE cap (line 1583) drops every critical/high finding past the 20th with only a transient log() line and no durable artifact, so those lessons are lost permanently. Every other truncation/budget path in this same file writes a deferred note — including the AGENT_CALL_BUDGET throw, to which this very wave added one (WC-003/RT-012) on the stated rationale that 'every other terminal exit path in this file does this'.
- fix: Write workspace/todos/deferred/<wave>-lrn-cap-exceeded.md containing toCodeify.slice(MAX_LRN_PER_WAVE) before continuing, mirroring the RT-012 budget-exceeded note; land in all three runners and pin with a test_workflows.py case.
- sdkCandidate: true

### RT-008
- **resolution: RESOLVED** — `JSON.parse(args)` is wrapped in try/catch at
  `.claude/workflows/wave-cycle.js:31-38`, rethrowing the attributed
  `wave-cycle: args arrived as a string but is not valid JSON` error. Pinned by
  `tests/test_workflows.py:3764` and
  `tests/test_rt_wave_cycle_budget_and_mismatch_fixes.py:120` (a different file
  than this finding's `fix:` proposed — the coverage is what matters).
- severity: low
- file: .claude/workflows/wave-cycle.js
- description: The GH-131 args normalization at line 26 calls JSON.parse(args) with no try/catch. GH-131's AC is to 'fail fast with a clear error naming the missing arg(s)', but a string args payload that is not valid JSON still dies with a bare SyntaxError naming neither the workflow nor waveFile/today — the same unactionable-error failure mode GH-131 set out to remove, one layer up. tests/test_gh131_wave_cycle_args_normalization.py asserts the pattern's presence but never this branch.
- fix: Wrap the parse in try/catch and rethrow as `wave-cycle: args arrived as a string but is not valid JSON — pass { waveFile, today } (or a JSON-encoded string of the same shape)`; add the matching assertion to tests/test_gh131_wave_cycle_args_normalization.py.
- sdkCandidate: true

### RT-009
- **resolution: RESOLVED** — `merged_annotations` no longer appears anywhere in
  `agent_sdk/agent/registry.py` (0 occurrences), and no
  `fake_client.meta.config.signature_version = ...` assignment remains in
  `tests/test_bedrock_credential_store.py`. The `signature_version` mentions
  still in that file are RT-013's own deliberate assertions about what the guard
  really probes, not the stale scaffolding this finding named.
- severity: low
- file: agent_sdk/agent/registry.py
- description: Dead code and stale scaffolding from the GH-134/GH-139 rework: registry.py:316 `merged_annotations = resolved_annotations` is a no-op alias kept only to preserve the old variable name at the ToolDecl(...) call site; and tests/test_bedrock_credential_store.py lines 62, 107 and 151 still set `fake_client.meta.config.signature_version = "bearer"` on MagicMocks even though the guard no longer reads that attribute (it now probes botocore.auth.AUTH_TYPE_MAPS), misdirecting a reader about what the guard actually checks — the exact readability failure the RT-013 test's own docstring documents.
- fix: Inline resolved_annotations directly into the ToolDecl(annotations=...) argument and delete the alias; remove the three stale fake_client.meta.config.signature_version assignments from tests/test_bedrock_credential_store.py.
- sdkCandidate: false

## Instruction

ONE finding remains open: **RT-001** (template/ peer-repo propagation), blocked
on a `template/` checkout that this working tree does not have. Everything else
is RESOLVED with landed evidence recorded above.

Close RT-001 by checking out the peer repo and running its `fix:`, then flip its
`resolution:` to RESOLVED and update the header — at which point LRN-100's sweep
relocates this file out of `deferred/`. Do NOT re-run the other eight as open
blockers.
