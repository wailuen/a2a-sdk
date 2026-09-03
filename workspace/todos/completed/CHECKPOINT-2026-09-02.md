# Checkpoint — 2026-09-02 22:38, before Claude Code restart (harness reload)

## ⚠️ CRITICAL — local `main` has diverged from `origin/main` by 14 commits

Discovered while writing this checkpoint (git fetch run, confirmed current):
`git rev-list --left-right --count HEAD...origin/main` → **3 ahead, 14 behind**.
Merge base is `65c6c5f` (the v0.5.44 release both branches share).

`origin/main` has moved to **v0.7.0** (via an intermediate v0.6.0) while this
local checkout is still at v0.5.45. Origin's history includes its own
**`fix/w039-gh-issues`** branch, merged and archived
(`52d349c fix(sdk): w039 — resolve GH-129/130/131/132/133/134/135/139`,
`a01f162 chore: archive w039 ...`) — **a completely different issue set**
(GH-129–135, 139) than this session's local w039 (GH-145/147/149/150).
Origin also has an OAuth org-wide-consent feature (GH-136/138) not present
locally.

**Wave-number collision:** this session's local `w039`/`w040` wave files
were numbered off the local `workspace/todos/completed/` directory (last
entry: w038), with no awareness that `origin/main` had already used and
archived its own `w039` independently — almost certainly from a different
session/worktree working on the same repo (`ListAgents` shows a peer
session `a2a-sdk-2b` marked busy at checkpoint time). Confirmed by
`git log origin/main --oneline | grep -iE "GH-14[5-9]|GH-150"` → **no
hits** — so GH-145/147/148/149/150 are NOT yet fixed on origin/main; this
session's work is not redundant, but it needs to be rebased/merged onto
current origin/main, not treated as a simple linear continuation of local
`main`.

**Do not push, merge, or rebase without the user's explicit direction.**
This checkpoint stops short of reconciling the two histories — that's a
decision for the user (rebase local work onto origin/main first? treat
local waves as a separate branch? renumber w039/w040 to avoid the
collision?).


Two wave-cycle workflows (w039, w040) were stopped mid-run so the terminal
could restart and pick up harness self-fixes (e.g. sdk-wave.js's
single-group Phase Redteam skip). **Workflow resumption is same-session
only** — a fresh session cannot `resumeFromRunId` these; the run IDs below
are for forensic reference only, not resumption.

## Working tree state at stop time

- Full test suite: **1637 passed, 2 skipped, 0 failed** (verified after
  stopping both — the tree was left in a green, coherent state on purpose).
- `git status --short` shows 106 modified/added paths, uncommitted — this
  is both w039's and w040's work interleaved in the same working tree (no
  isolation was used between the two concurrent runs).
- Nothing has been committed since the two earlier commits on `main`
  (95d4fc7 wave-cycle.js sync, fd0aea1 RT-004/RT-012 fix, both already
  pushed... actually NOT pushed — verify before assuming remote state).

## w039 — GH-147, GH-145, GH-149, GH-150

- Wave file: `workspace/todos/active/w039-gh-issues.md`
- Run ID: `wf_60ff7daa-77b` (task `wnaulksfr`, stopped cleanly, NOT resumable in a new session)
- Last completed step before stop: fixing RT-B-010
  (`tests/test_rtb003_taskstore_persist_status_hook.py`) — a store-aliasing
  bug where `_CopyOnGetStore.get()` only deep-copied `task`, not
  `messages`/`pending_tool_results`, letting an in-place repair reach
  durable storage without going through `persist_messages`.
- Phase reached: still inside the Phase Redteam fix loop (post-implement,
  pre-archive). NOT yet archived — wave file is still in `active/`.
- New/modified files include: `agent_sdk/routes/a2a.py`,
  `agent_sdk/agent/loop.py`, `agent_sdk/agent/runner.py` (new
  `repair_dangling_tool_use` helper, registered as component **C-018** in
  `workspace/components/README.md`), `agent_sdk/tasks/store.py` (new
  `TaskStore.persist_messages` + `TaskRecord.pending_tool_results`),
  `agent_sdk/models/content_types.py` + `agent_sdk/a2ui/catalog.py`
  (GH-149 `fund_name` removal), `agent_sdk/agent/bedrock.py` (GH-145 fix).

## w040 — GH-148 (Reusable/ReuseKind mechanism)

- Wave file: `workspace/todos/active/w040-gh-issues.md`
- First run ID: `wf_98abb0b1-e8e` (task `wgq12vlo6`) — stopped once,
  **resumed in the SAME session** under the same run ID (task `wfsszpdyk`)
  once the sdk-wave.js self-fix (skip Phase Redteam for single-group
  waves) landed on disk, so cached implement/unit-redteam results carried
  forward without redoing work. Stopped a second time for this checkpoint
  — also NOT resumable in a new session.
- Last completed step before stop: rewriting
  `workspace/learning/README.md` to index all 151 LRN records (14 were
  missing: LRN-138–151; 9 files use non-standard frontmatter). This is
  Codify-phase work — implementation and redteam rounds were already done.
- Phase reached: Codify (late-stage, near Archive). NOT yet archived —
  wave file is still in `active/`.
- New module: `agent_sdk/agent/reuse.py` (`Reusable` dataclass,
  `ReuseKind` marker) — the GH-148 mechanism itself. Extensive new test
  coverage under `tests/test_rt0*_reuse_*.py`, `tests/test_gh148_*.py`,
  `tests/test_context_reusable_messages.py`.

## To resume after restart

Both waves are unfinished (not archived). The clean way to continue in the
new session:
1. Re-verify the working tree is still green: `pytest -q` (was 1637
   passed / 2 skipped at stop time — confirm nothing regressed from any
   external change).
2. Run `/wave w039` and `/wave w040` again — each will start a **new**
   workflow run against the current wave file + current (already-mutated)
   working tree. This is NOT a resume of the stopped runs; expect the
   Todos Redteam / Implement phases to re-detect that most work is already
   done (files exist, tests pass) rather than redo it from scratch, but
   this has not been verified — watch the first few phases closely.
3. Delete this checkpoint file once both waves have archived cleanly.
