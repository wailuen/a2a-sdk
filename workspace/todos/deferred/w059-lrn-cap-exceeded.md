# w059 — LRN capture cap exceeded

- Wave: w059
- Date: 2026-10-22
- MAX_LRN_PER_WAVE: 20
- Overflow findings: 8

These findings were already fixed but not codified as LRN files due to the 20-per-wave cap. Review and codify opportunistically, or fold into a future wave.

| # | ID | Severity | File | SDK candidate |
|---|----|----------|------|---------------|
| 1 | RT-002 | high | agent_sdk/testing/turns.py | yes |
| 2 | RT-003 | high | agent_sdk/testing/turns.py | yes |
| 3 | RT-004 | high | harness/workflows/acceptance-api.js | yes |
| 4 | RT-005 | high | CHANGELOG.md | yes |
| 5 | RT-006 | high | template/.claude/workflows/acceptance-api.js | yes |
| 6 | RT-001 | high | template/.claude/skills/acceptance/SKILL.md | yes |
| 7 | RT-001 | high | template/.claude/workflows/wave-cycle.js | yes |
| 8 | RT-002 | high | CHANGELOG.md | yes |

## 1. RT-002 — agent_sdk/testing/turns.py (high)

**Description:** The rate-limit text check runs on successful reply bodies (line 113, `any(t in self.reply.lower() for t in _RATE_TEXT)`). A completed A2A or AG-UI answer that just mentions 'rate limit' or 'too many requests' (for example 'Our API rate limit is 100 req/min.') is classified as rate-limited. It is retried until the budget runs out and comes back as failureClass 'rate-limited'. Verified with an httpx MockTransport probe: ok=False, reason too-many-requests. Together with RT-001, a correct agent answer becomes an untested pass, and a wrong one gets hidden.

**Fix:** Only match rate-limit text on error channels: an AG-UI RUN_ERROR message (the `errors` list), or the status message of an A2A task in failed/rejected state. Never match it on a completed reply. Add tests: a completed reply containing 'rate limit' gives ok=True on the first attempt; a RUN_ERROR 'too many requests' is retried.

**Codify:** Match retry heuristics against error signals only, never against the content of a successful answer.

## 2. RT-003 — agent_sdk/testing/turns.py (high)

**Description:** The 'total budget under 600 s' acceptance criterion (AC) is not enforced. The deadline is only checked before slot acquire (line 282) and before back-off (line 305). An in-flight attempt is never bounded: the client uses httpx timeout=300 (line 263), which limits each read, not the whole stream. Slot wait can use up to about 540 s and then start an attempt that runs 300 s or more, so one call can pass 840 s. test_total_budget_enforced fakes the clock with zero-length attempts, so it cannot catch this.

**Fix:** Wrap each attempt in `asyncio.wait_for(..., timeout=max(0, deadline - _now()))`. On timeout, classify reason 'budget-exceeded' and restore AG-UI messages. Also cap the httpx timeout at the remaining budget. Add a test with a handler or stream that stalls past the remaining budget, and assert that run_turn returns within budget.

**Codify:** A total time budget must bound the work in flight, not just the gaps between attempts.

## 3. RT-004 — harness/workflows/acceptance-api.js (high)

**Description:** The scenario prompt (lines 111-115 and 151-155) tells agents to run the helper through Bash, whose default timeout is 120 s. It never says to raise the Bash timeout to cover the helper's 540 s budget. With 3 slots shared by 30+ scenarios on 2 transports, slot waits plus back-off will often pass 120 s. The tool kills the helper, no JSON is printed, and RULES line 199 ('network timeout — score the turn 1') applies. That recreates the exact GH-210 symptom (throttled turns scored 1-2).

**Fix:** In both helper instructions, require running the Bash command with timeout 600000 (ms) and state that the helper always prints one JSON line before 600 s. Add a sync test that pins this wording in buildScenarioPrompt.

**Codify:** When a prompt hands a long-running helper to the Bash tool, it must state a Bash timeout of at least the helper's own budget.

## 4. RT-005 — CHANGELOG.md (high)

**Description:** There is no GH-210 entry under [Unreleased]. The todo lists CHANGELOG.md in Creates and says 'Each item adds its own entry'. New public exports `run_turn` and `SlotLimiter` (agent_sdk/testing/__init__.py __all__), the CLI `python -m agent_sdk.testing.turns`, and the new acceptance failure class 'rate-limited' are all undocumented. This fails the LRN-202 Check (newly exported symbols need an ### Added line; severity high).

**Fix:** Add an ### Added entry for GH-210. Cover: the agent_sdk.testing.turns run_turn/SlotLimiter API and CLI flags; the default of 3 slots and 540 s budget; key-file-only credential handling; the 'rate-limited' failure class in acceptance-api.js and the SKILL; the template needing agent-sdk >=0.18.0; and the test file.

**Codify:** Every todo that adds an __all__ export must land its own CHANGELOG ### Added line in the same group.

## 5. RT-006 — template/.claude/workflows/acceptance-api.js (high)

**Description:** The template mirror commit f713e7b is only on origin/feat/gh210-acceptance-turn-helper. `git -C template log origin/main -1` shows 02555da (GH-211), not the GH-210 commit, and `git -C template status --short` is not empty. This fails the LRN-290 Check (severity high): downstream agents scaffold from template main and do not get the helper wiring or the rate-limited class.

**Fix:** Open and merge a template pull request to main after agent-sdk 0.18.0 is tagged (the pin depends on it). Or record an explicit release-gated staging decision (issue URL) in the todo, so the LRN-290 Check has a ratified exception. Then re-run the Check.

**Codify:** A template mirror pushed to a side branch is not delivered. Either merge it to main or record a ratified release-gated exception.

## 6. RT-001 — template/.claude/skills/acceptance/SKILL.md (high)

**Description:** [SDK] The Phase 1.5 hunk is committed (fd21b8e) and pushed only to the feature branch origin/feat/gh210-acceptance-turn-helper, which has no PR. Remote main is still at 02555da, and `git -C template diff origin/main --stat -- .claude/skills/acceptance/SKILL.md` shows +67/-1. Downstream agents that sync the template from main never receive the gate. This fails the LRN-335 Check (template clean against origin/main; severity high) and the LRN-314 intent.

**Fix:** Open a PR on wailuen/a2a-agent-template from feat/gh210-acceptance-turn-helper to main, or push to main as the delivery step. Do not mark GH-209 done until `git -C template diff origin/main -- .claude/skills/acceptance/SKILL.md` is empty. Add an archive-gate check for this diff.

**Codify:** Pushing the template mirror to a feature branch with no PR is not delivery. The gate is a diff against origin/main (LRN-335), not 'git push succeeded'.

## 7. RT-001 — template/.claude/workflows/wave-cycle.js (high)

**Description:** [SDK] The template mirror deliverables for GH-208, GH-209, GH-210 and GH-211 are not delivered. template/ is on branch feat/gh210-acceptance-turn-helper (HEAD fd21b8e). That HEAD is not an ancestor of origin/main and also lacks origin/main's GH-211 commit 02555da. The working tree has uncommitted edits to .claude/workflows/wave-cycle.js and acceptance-api.js. template/.claude/agents/core/redteam.md differs from harness/agents/core/redteam.md at line 175 (the stale-rule wording). tests/test_wave_scope_extraction.py::test_gh164_template_mirror_is_committed_and_pushed FAILS. The LRN-335 Check fails because `git -C template status --short` is not empty. The todo ACs say all mirrors are committed and pushed to wailuen/a2a-agent-template as the final step.

**Fix:** In template/, rebase or merge the feature branch onto origin/main so it includes 02555da. Sync redteam.md byte-identical to the harness copy, commit the two dirty workflow files, push, and merge the template PR into main. Then re-run test_gh164_template_mirror_is_committed_and_pushed and tests/test_workflow_sync.py.

**Codify:** A template mirror counts as delivered only when the template HEAD is clean and reachable from origin/main. A pushed feature branch or a byte-identical working copy is not delivery (re-confirms LRN-335).

## 8. RT-002 — CHANGELOG.md (high)

**Description:** [SDK] The LRN-433 Check fails. The [Unreleased] section never names these changed agent_sdk files: loop.py, runner.py, a2a.py (where the new public helper cancel_task_record now lives), ag_ui.py and testing/__init__.py. Several statements are also wrong. Line 10 (GH-221) tells clients they 'must send a valid Mcp-Session-Id' on GET /mcp, but no header still returns 200. Line 14 (GH-204) gives the test as tests/test_gh209_testing_mcp.py, but GH-204's test is tests/test_rt003_rt004_mcp_error_mapping.py. The GH-221 entry is filed under 'Breaking changes', while the AC asks for 'Changed'.

**Fix:** Name every changed agent_sdk file in its entry (GH-220: loop.py, runner.py, ag_ui.py; GH-217: a2a.py with cancel_task_record, ag_ui.py; GH-209/210: testing/__init__.py). Fix the GH-221 migration sentence to say the header is optional and checked only when present. Fix the GH-204 test path. Reconcile the heading with the AC, or record why it moved.

**Codify:** Run the LRN-433 basename check against CHANGELOG [Unreleased] before a wave's phase redteam closes. Every helper moved into a new module counts as a changed file to name.
