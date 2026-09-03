# w039 — GitHub issues #145, #147, #150

Sourced from open issues on wailuen/a2a-sdk. Target: v0.5.45.

**Non-standard grouping** (deviates from "all items independent, run in
parallel"): GH-147 and GH-150 both touch `run_loop`'s message-fold
invariants — record.messages must stay Converse-valid (correctly
alternating roles, every toolUse immediately followed by its toolResult)
before A2A contextId continuation replays it. Two independent triage
passes flagged this coupling. GH-147 is the more foundational fix (folds
the final assistant turn that's missing today); GH-150 (repairs a
cancellation-induced dangling toolUse) must land and be tested against
GH-147's already-updated fold logic, not develop against the pre-147
baseline. So: group:A runs first (GH-147, GH-145 — no file overlap between
them), group:B runs after group:A completes (GH-150).

---

- [x] `GH-147` A2A contextId continuation never replays the model's own prior-turn replies ‖ group:A
  - Modifies: `agent_sdk/agent/loop.py`
  - Reads: `agent_sdk/routes/a2a.py`, `agent_sdk/tasks/memory.py`, `agent_sdk/routes/ag_ui.py`
  - Severity: critical
  - Root cause: `run_loop` returns on the no-tool-call branch (`loop.py:371-373`) before the assistant-turn fold block (`loop.py:375-389`) runs — that fold only executes on the tool-call path. A completed task's `record.messages` therefore never contains the model's own final plain-text reply (it only reaches the wire via `status.message`), so A2A contextId continuation (`routes/a2a.py`'s `context_messages()` replay) never shows the model what it said last turn. Secondary defect, same root cause: a tool-using task's stored transcript always ends on the `user` toolResult message, and continuation appends another `user` message — two consecutive `user`-role entries, malformed for Converse-shaped backends. AG-UI is unaffected (it folds the client-resent transcript, never calls `context_messages()`).
  - AC: Before the early `return` in the no-tool-call branch, fold `{"role": "assistant", "content": [...text segments...]}` into `messages` (no toolUse blocks; skip the fold if all segments are empty/whitespace).
  - AC: A completed no-tool-call task's stored `record.messages` contains the assistant's final reply, and a subsequent contextId-continuation turn's replayed prior history includes it.
  - AC: For a tool-using task, the stored transcript has no two consecutive same-role messages at any turn boundary, including across a contextId-continuation append (assistant(toolUse) → user(toolResult) → assistant(final text) → [continuation] user(next turn)).
  - AC: AG-UI's client-supplied-history path is unaffected (regression assertion optional but preferred).
  - GH: https://github.com/wailuen/a2a-sdk/issues/147
  - Reuses: C-017  # AC3's "no two consecutive same-role messages" invariant already has a registered home: C-017's bridge_trailing_user (agent_sdk/agent/loop.py:244). The new no-tool-call branch must call it (for the all-empty-segments case where there is nothing to fold) rather than inlining a role check at the new early return, and the same helper — not a second copy — must close the transcript at every other run_loop exit (deadline, token budget, upstream AgentError, max-turns). Name C-017 in the todo so the fix lands as one shared call-site set.
  - Reuses: C-005  # AC2 claims the STORED record.messages carries the assistant's final reply, but run_loop mutates the TaskRecord's list by reference and run_task_worker's COMPLETED path (agent_sdk/agent/runner.py:1038-1044) calls only _set_status/persist_status — never TaskStore.persist_messages, the C-005 write hook, whose only call site today is inside repair_dangling_tool_use (runner.py:493). On any durable copy-on-get TaskStore (the AzureTableTaskStore shape C-005 exists for) the newly folded assistant turn is dropped and context_messages() replays a transcript without it, so AC2 holds for InMemoryTaskStore only. Add an AC that the normal completion path flushes through the C-005 persist_messages hook, or state the live-reference requirement explicitly in the C-005 contract and registry description.
  - SI: SI-2  # No SI: field on the todo, but the AC persists new content into record.messages, which contextId continuation replays back to the model on every later turn and which reaches logs. Two SI-2 obligations must be explicit ACs, not left to the implementer: (1) the placeholder appended when all text segments are empty/whitespace must be a fixed SDK-authored constant (loop.py's _TRAILING_USER_BRIDGE_TEXT), never derived from model output, tool arguments, a tool result payload, or an upstream exception string (no str(exc) on the wire); (2) the folded assistant content must carry text segments only, never toolUse input echoes. Per LRN-128, name the regression test in the todo rather than describing it.

- [x] `GH-145` BedrockModelClient bearer-token auth raises NoCredentialsError on Linux ‖ group:A
  - Modifies: `agent_sdk/agent/bedrock.py`
  - Reads: `tests/test_bedrock_credential_store.py`
  - Severity: high
  - Root cause: botocore's `_set_auth_scheme_preference_signer` decides bearer-vs-sigv4 signing by reading the REAL process `os.environ.get('AWS_BEARER_TOKEN_BEDROCK')` directly — it never consults the SDK's isolated, registered `token_provider` component. Since `_boto_client()` deliberately never writes the token to the real env (SI-6), that gate always evaluates False, signing falls back to sigv4, and sigv4 requires real IAM credentials that don't exist in a bearer-only deployment → `NoCredentialsError`. This is not a macOS-vs-Linux botocore difference — macOS only "worked" if `AWS_BEARER_TOKEN_BEDROCK` happened to be present in that machine's real env (itself a quiet SI-6 leak), while Linux correctly has no such var and fails honestly.
  - AC: In the `bearer_token` branch of `_boto_client()`, pass `config=botocore.client.Config(signature_version="bearer")` to `boto_session.client("bedrock-runtime", **kwargs)` so signer selection no longer depends on the real env var; SI-6 isolation is preserved (no `os.environ` writes).
  - AC: New regression test asserts the resolved client's `meta.config.signature_version == "bearer"`.
  - AC: New regression test monkeypatches `os.environ` to NOT contain `AWS_BEARER_TOKEN_BEDROCK` (simulating the Linux case) and asserts `_boto_client()` still resolves to bearer auth rather than falling through to sigv4.
  - AC: Module docstring updated to record why `signature_version` must be pinned explicitly in code (so a future simplification doesn't silently reintroduce the env-var-sniffing path).
  - GH: https://github.com/wailuen/a2a-sdk/issues/145
  - SI: SI-6  # No SI: field on the todo, but it is the Bedrock bearer-token credential path (agent_sdk/agent/bedrock.py:71-91). SI-6 must be an explicit AC, not prose inside the root cause: the config=Config(signature_version="bearer") change must not touch the isolated single-key dict at bedrock.py:84, must not write AWS_BEARER_TOKEN_BEDROCK to os.environ or argv, and the new tests must never print or assert the token value. Per LRN-128 (SI-tagged AC landed without its mandated regression test), name the regression test in the todo rather than describing it.
  - SI: SI-4  # Credential is resolved, not read: app.py:387 pulls bearer_token from credential_store.get(NS_BEDROCK, "bearer_token"). The fix must not introduce an os.environ.get("AWS_BEARER_TOKEN_BEDROCK") read or fallback while making signer selection deterministic — AC-3 monkeypatches os.environ for the test only and that must not leak into production code. Add an explicit AC: no os.environ / os.getenv read of a credential in bedrock.py after the change.

- [x] `GH-149` FundPerformance.fund_name silently extends the Standard Profile v1 frozen field contract ‖ group:A
  - Modifies: `agent_sdk/models/content_types.py`, `agent_sdk/a2ui/catalog.py`, `agent_sdk/console/static/a2ui.js` (RT-010 follow-on: `renderFundPerformance` lost its `fundName`-derived title when the field was deleted, fell back to the opaque `pbId` source id — retitled to the neutral "Fund performance" with `pbId` demoted to subtitle provenance, see AC below); `.claude/agents/a2ui-advisor.md`, `harness/agents/a2ui-advisor.md`, `template/.claude/agents/a2ui-advisor.md` (RT-003 amendment: originally scoped here as Reads-only/"parity check only, not modified" — a later GH-149 follow-up (RT-005/RT-006, REVIEWS.md Round 8, w040) actually edited these three copies, deleting `TimeSeriesChart`'s stale typed `metadata` row and adding an SDK-wide cross-cutting note; Round 8 records that change as PROPOSED pending maintainer ratification, not SIGNED OFF — see `tests/test_rt002_a2ui_wire_shape_mirror_parity.py`'s `ROUND_8_METADATA_ROW_REMOVAL_RATIFIED` gate)
  - Severity: high
  - Root cause: `FundPerformance.fund_name` (wire alias `fundName`, `content_types.py:570`) is not among the 19 fields in the frozen A2UI Standard Profile v1 `FundPerformance` contract (`.claude/agents/a2ui-advisor.md:468-492`), yet it shares the same `catalog_id` (`urn:a2ui-profile:standard:v1`) as every other frozen type — no gating/versioned-extension mechanism exists to mark it as an intentional addition. Developer decision: **remove the field** (this is a breaking change for any agent already emitting `fundName` on the wire).
  - AC: Delete `fund_name: str | None = Field(default=None, alias="fundName")` from `FundPerformance` (`content_types.py:570`).
  - AC: Remove the `if self.fund_name: bits.append(self.fund_name)` branch from `FundPerformance.to_plain_text()` (`content_types.py:596-597`) and confirm the remaining bits (IRR/TVPI/DPI/etc.) still produce a non-empty summary on their own.
  - AC: Update the LLM-facing example payload (`agent_sdk/a2ui/catalog.py`, `_FEW_SHOT_EXAMPLES["FundPerformance"]` — cited by name, not line: pinned line numbers rot as the module grows, per C-017's registry note) and the compact wire schema (`catalog.py`, `_COMPACT_SCHEMAS["FundPerformance"]`) to drop `fundName` from both.
  - AC: Update `tests/test_content_types.py` (and any other test fixture referencing `fund_name`/`fundName`) to match the new field set; add a regression test asserting `FundPerformance` rejects/ignores `fundName` construction via the model's declared field set (i.e. it's genuinely gone, not just undocumented).
  - AC: CHANGELOG.md entry under a `🔴 Breaking changes` heading (per this project's existing convention — see the 0.5.44 GH-128 precedent) with a Migration callout: any agent emitting `fundName` on `FundPerformance` must drop it; the field carried no A2UI Standard Profile v1 conformance guarantee.
  - AC: `renderFundPerformance` in `agent_sdk/console/static/a2ui.js` titles the card `"Fund performance"` unconditionally (never the raw `pbId` upstream source id, which is provenance not a display name); when `data.pbId` is present it appears in the subtitle alongside `asOfDate` instead.
  - GH: https://github.com/wailuen/a2a-sdk/issues/149

- [x] `GH-150` Cancelling a task mid-tool-call leaves an unmatched toolUse block that context continuation replays ‖ group:B
  - Modifies: `agent_sdk/routes/a2a.py`, `agent_sdk/agent/runner.py`, `agent_sdk/tasks/store.py`  # RT-B-004: fix landed as `repair_dangling_tool_use` (runner.py:329-465, net-new) plus `TaskStore.persist_messages` + `TaskRecord.pending_tool_results` (store.py); amended post-landing so wave/redteam scope (Creates+Modifies) matches what shipped — runner.py was previously Reads-only, store.py was in neither list.
  - Reads: `agent_sdk/agent/loop.py`, `agent_sdk/tasks/memory.py`
  - Severity: high
  - Root cause: `run_loop` is called with `messages=record.messages` (shared by reference). The assistant `toolUse` message is appended at `loop.py:389`; the matching `toolResult` is only appended after the full per-tool-call loop completes. `run_task_worker`'s `CancelledError` handler deliberately re-raises without repairing `messages`, documenting that "the canceller owns cleanup" — but `tasks_cancel` (`routes/a2a.py`) cancels the worker and sets status to CANCELED without ever inspecting/repairing `record.messages`. `context_messages()` then replays the broken transcript verbatim, which Converse-API-shaped backends (Bedrock) reject outright.
  - AC: In `tasks_cancel`, after setting status to CANCELED, detect an unresolved toolUse tail (last message is `assistant` with toolUse block(s) lacking a following matching toolResult) and append a synthetic `{"role": "user", "content": [{"toolResult": {...status: "error", text noting cancellation...}}]}` for each unresolved toolUseId.
  - AC: New test starts a task with a slow/blocking tool call, cancels it mid-flight, and asserts `record.messages` ends with the assistant toolUse message immediately followed by a matching error toolResult for every toolUseId in that turn.
  - AC: New/extended test exercises `context_messages()` (or the a2a.py contextId-continuation path) after such a cancellation and asserts the replayed transcript never contains a toolUse without an immediately-following matching toolResult.
  - AC: CHANGELOG.md entry in the repo's existing GH-XXX format.
  - GH: https://github.com/wailuen/a2a-sdk/issues/150
  - Reuses: C-005  # The AC repairs record.messages in-place from inside the tasks_cancel route handler (routes/a2a.py:393-421). record.messages is TaskStore-owned state and the C-005 ABC (agent_sdk/tasks/store.py) exposes no write/persist hook — InMemoryTaskStore works only because get() hands back the live object by reference. Any external durable subclass (the AzureTableTaskStore case C-005 exists for) will silently drop the repair, so the broken transcript survives in the durable store and context_messages() replays it anyway. Either add the repair as a TaskStore method (mirroring how mark_interrupted/deliver_resume mutate record state through the ABC) or state the in-place-mutation requirement explicitly in the C-005 contract and its registry description.
  - Reuses: C-007  # The synthetic toolResult text ("text noting cancellation") is an error string that goes back to the model and into logs. If it interpolates the model-supplied tool name it must reuse the truncate + control-char-strip pattern that C-007 safe_error_text is registered to consolidate — already implemented in this exact file family as _sanitize_model_name (agent_sdk/agent/loop.py:62-65, used at loop.py:407 and 425). C-007 is still status=planned and agent_sdk/common/redact.py only masks secret-named keys, not control chars, so do not hand-roll a fourth divergent copy: either land C-007 in this todo or import _sanitize_model_name.
  - SI: SI-5  # No SI: field, but the todo modifies an authenticated A2A transport route. tasks_cancel gates on Depends(require_identity) (a2a.py:394), guard_origin(request) (a2a.py:396) and the identity-scoped store.get(task_id, identity) (a2a.py:398). Add an AC that the transcript-repair code runs strictly after those three checks and introduces no new route or pre-auth branch; wave-cycle classifies routes/a2a.py in A2A_SURFACE + AUTH_SURFACE (C-014), so it will be audited against this either way.
  - SI: SI-2  # The synthetic toolResult content is replayed to the model on the next contextId turn and can reach logs. Add an AC that its text is a fixed SDK-authored string and never embeds tool arguments, the tool result payload, or an upstream exception string (no str(exc) on the wire).
  - Reuses: C-018  # AC1 describes hand-rolling the synthetic-toolResult fold inside tasks_cancel. C-018 repair_dangling_tool_use (agent_sdk/agent/runner.py:357) is the registered single repair helper for exactly this, with a documented override/pending_tool_results/default precedence and five existing call sites; tasks_cancel must call it with store= so the C-005 flush runs, not inline a sixth divergent copy. Rewrite AC1 to name the helper.
  - Reuses: C-017  # The ACs cover only the dangling-toolUse tail. C-017's bridge_trailing_user must run after the repair UNCONDITIONALLY — including when there was no dangling tail — because a cancelled transcript can already end on a plain user toolResult message, which contextId continuation then follows with a second user turn. Add that as its own AC and route it through C-017 rather than a role check written inside the route handler.

---

## Surfaced, NOT in this wave (developer decision needed)

- **GH-148** (no structural mechanism to thread a resolved identifier across
  turns, high) — confirmed real, live production data-correctness failure
  (7/8 fresh test runs substituted the same wrong-but-valid ID). Two
  structurally different fix directions on the table (model-facing
  reuse/handle primitive vs. exposing conversation/task state to tool
  bodies), each with real architectural tradeoffs to the tool-calling
  contract. No fix chosen yet.

  Update: chosen and landed as w040 (GH-148, `agent_sdk/agent/reuse.py`),
  which ran concurrently with this wave against the same uncommitted working
  tree (see `CHECKPOINT-2026-09-02.md`, archived alongside this file). Its
  changes are interleaved with this wave's in commit `5b669b3`.

---

## Archival note (RT-002 follow-up)

**Correction (RT-001, post-archive):** the paragraph below originally read "All
four ACs above landed in code with passing regression tests" without
qualification. That is true of the code/test ACs only. GH-149's CHANGELOG AC
("CHANGELOG.md entry under a 🔴 Breaking changes heading … with a Migration
callout") and GH-150's CHANGELOG AC ("CHANGELOG.md entry in the repo's
existing GH-XXX format") were NOT part of commit `5b669b3` —
`git show 5b669b3:CHANGELOG.md` (and `231e370`, the commit that archived this
file) both top out at `[0.5.44]`, with no entry for GH-145/147/149/150. The
corrected CHANGELOG.md text (and a related DESIGN.md §4.3 fix, since §4.3
described the pre-refactor `to_plain_text()` contract this same code line
later changed) sat as an uncommitted working-tree draft as of this
correction. Check a doc-file AC against `git show <landing-commit>:<file>`,
never against the working tree — see LRN entry filed alongside this
correction.

All four code/test ACs above landed in code with passing regression tests
before this wave's own Phase Redteam reached Archive — see the two
`w039-group-{A,B}-budget-exhausted.md` deferred notes (archived alongside
this file) for the 12 findings raised against the round-5 state and their
fixes, all since verified against current code. The wave stalled short of self-archiving
because a second wave (w040, GH-148) started its own Implement phase
against this same working tree before this one committed, per
`CHECKPOINT-2026-09-02.md` — leaving 106+ modified/added paths uncommitted
and interleaved across both waves with no isolation. Full suite green
(1877 passed, 3 skipped, 0 failed) and mypy clean on the commit that lands
this work: `5b669b3`. `agent_sdk/agent/loop.py`, `agent_sdk/agent/runner.py`,
`agent_sdk/tasks/store.py` and `agent_sdk/routes/a2a.py` carry both this
wave's GH-147/GH-150 fixes and w040's GH-148 mechanism inseparably — a
hunk-level split was assessed and found unsafe to do by hand (see the
commit message). `sdk-wave.js`/`wave-cycle.js` now refuse to start a second
wave's Implement phase while another wave file sits in
`workspace/todos/active/` with an uncommitted working tree, closing the gap
that allowed this.
