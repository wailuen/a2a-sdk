# w059 — group G6 — tests RED (round 1)

- Wave: w059
- Scope: unit:G6
- Date: 2026-10-22
- Round: 1
- Reason: test suite RED after the fix attempt; blocking findings below remain unresolved.
- Instruction: Fix failing tests and remaining findings, then re-run /wave w059

## Unresolved blocking findings

### RT-001 (high) — harness/workflows/acceptance-api.js
Fail-open pass gate. Line 198 tells the scenario agent "If every turn on a transport was rate-limited, score that transport 10"; line 102 makes both transports >=7 mean passed=true. A scenario with no answered turn can pass. Contradicts SKILL.md:489. Workflow code only counts rate-limited results (~line 275), never overrides passed.
- Fix: after the pipeline force passed=false for failureClass==='rate-limited' and report as "not run". Prompt: replace "score that transport 10" with "leave minScore unset/0, passed=false, failureClass rate-limited". Add behaviour test: rate-limited never counted as passed.
- Codify: an excluded/infrastructure failure class must never turn into a pass. Untested turns are "not run", not 10/10.
- sdkCandidate: true

### RT-002 (high) — agent_sdk/testing/turns.py
Rate-limit text check runs on successful reply bodies (line 113, `any(t in self.reply.lower() for t in _RATE_TEXT)`). A completed answer mentioning "rate limit" / "too many requests" is retried to budget exhaustion and returned as failureClass rate-limited (verified with httpx MockTransport: ok=False, reason too-many-requests).
- Fix: match rate-limit text only on error channels (AG-UI RUN_ERROR `errors` list; A2A failed/rejected status message). Tests: completed reply with "rate limit" -> ok=True first attempt; RUN_ERROR "too many requests" -> retried.
- Codify: match retry heuristics against error signals only, never successful answer content.
- sdkCandidate: true

### RT-003 (high) — agent_sdk/testing/turns.py
"Total budget under 600 s" AC not enforced. Deadline checked only before slot acquire (line 282) and before back-off (line 305). httpx timeout=300 (line 263) is per-read, not whole-stream. One call can exceed 840 s. test_total_budget_enforced uses zero-length attempts, so cannot catch it.
- Fix: wrap each attempt in `asyncio.wait_for(..., timeout=max(0, deadline - _now()))`; on timeout reason "budget-exceeded" and restore AG-UI messages; cap httpx timeout at remaining budget. Test with a stalling handler/stream; assert run_turn returns within budget.
- Codify: a total time budget must bound in-flight work, not just the gaps between attempts.
- sdkCandidate: true

### RT-004 (high) — harness/workflows/acceptance-api.js
Scenario prompt (lines 111-115, 151-155) runs the helper via Bash (default 120 s timeout) without raising it to cover the 540 s helper budget. With 3 slots shared by 30+ scenarios x 2 transports, waits exceed 120 s, the helper is killed, no JSON is printed, and RULES line 199 scores the turn 1 — recreating GH-210.
- Fix: both helper instructions require Bash timeout 600000 ms and state the helper always prints one JSON line before 600 s. Add a sync test pinning this wording in buildScenarioPrompt.
- Codify: when a prompt hands a long-running helper to Bash, state a Bash timeout >= the helper's budget.
- sdkCandidate: true

### RT-005 (high) — CHANGELOG.md
No GH-210 entry under [Unreleased]. New exports `run_turn`, `SlotLimiter` (agent_sdk/testing/__init__.py __all__), CLI `python -m agent_sdk.testing.turns`, and failure class "rate-limited" undocumented. Fails LRN-202 Check.
- Fix: add ### Added entry for GH-210: run_turn/SlotLimiter API and CLI flags; defaults 3 slots / 540 s; key-file-only credentials; "rate-limited" class in acceptance-api.js and SKILL; template needs agent-sdk >=0.18.0; the test file.
- Codify: every todo adding an __all__ export lands its own CHANGELOG ### Added line in the same group.
- sdkCandidate: true

### RT-006 (high) — template/.claude/workflows/acceptance-api.js
Template mirror commit f713e7b is only on origin/feat/gh210-acceptance-turn-helper. `git -C template log origin/main -1` shows 02555da (GH-211); `git -C template status --short` not empty. Fails LRN-290 Check: downstream agents scaffold from template main without the helper wiring or rate-limited class.
- Fix: merge a template PR to main after agent-sdk 0.18.0 is tagged, or record a ratified release-gated staging decision (issue URL) in the todo; re-run the Check.
- Codify: a template mirror on a side branch is not delivered — merge to main or record a ratified release-gated exception.
- sdkCandidate: true

## Shared working tree rule
Other agents have uncommitted work in this tree. NEVER run `git stash`, `git reset`, `git checkout -- <path>`, `git restore`, `git clean` or `git checkout .`. Edit files in place; inspect old content with `git show` / `git diff`.
