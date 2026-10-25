---
name: sdk-autoloop
description: "Hands-off SDK maintenance loop: auto-file verified findings from the last wave → /gh-review --auto (take recommended rulings, post them, label deferred) → sdk-wave → /sdk-release → close issues → repeat, until no open issue on wailuen/a2a-sdk lacks the `deferred` label. Bounded by a cycle cap and a convergence check. Use when the developer asks to run the loop unattended."
---

# /sdk-autoloop — file → review → wave → release, until only deferred issues remain

Invoking this skill is the developer's durable authorization, for this run only, to:
file issues, post rulings, run waves, commit, tag, push, and close issues **without
per-step confirmation**. It does not carry over to a later session.

## Usage

```
/sdk-autoloop                 — run until done (default cap: 5 cycles)
/sdk-autoloop --cycles <n>    — change the cap
/sdk-autoloop --no-file       — skip the auto-file step (work only the open issues)
```

## Definitions

- **Deferred issue** — an open issue with the `deferred` label. The loop never works it.
  A label is applied only by a ruling comment (step 2c) or by the developer.
- **Done** — `gh issue list -R wailuen/a2a-sdk --state open --search "-label:deferred"`
  returns nothing **and** the last auto-file step filed nothing.
- **Fileable finding** — critical, high or medium; verified still present in the current
  code; SDK-level (inside `agent_sdk/`, `harness/`, `template/`, `.claude/`, docs);
  not a duplicate of an open or recently closed issue. Lows are never filed — they stay
  in `workspace/todos/deferred/`. From cycle 4 on, only critical/high are filed (damping).

## The cycle

### 1. Auto-file (skip with `--no-file`)

a. Sources, newest wave only (`wNNN` = the most recent wave in `workspace/todos/completed/`):
   `workspace/todos/deferred/wNNN-*-medium-low.md`, `wNNN-protocol-medium.md`,
   any `wNNN-*-budget-exhausted.md`, and `workspace/sdk-candidates.md`.
   Never re-scan an older wave's files — that is how the loop terminates.
b. Verify against the code. Dispatch one `general-purpose` agent per 2–3 source files, in
   parallel. Each reads the finding, reads the cited code, and returns
   `{id, severity, still_present: bool, evidence: "path:line", root_cause_key}`.
   The `sdk-candidates.md` "still-open" status is usually stale — never trust it unverified.
c. Merge findings that share a `root_cause_key` or touch the same function into one issue.
   Group small related items into one issue per surface (e.g. "console: chat.js
   hardening"), at most 10 issues per cycle.
d. Dedupe: `gh issue list -R wailuen/a2a-sdk --state all --search "<key terms>" --limit 5`.
e. File with the `/sdk-issue-scan` body template, `--label bug`, no credentials, no
   quoted secrets. Record each URL in the source file next to the finding (`Filed: #N`).
f. Archive `workspace/sdk-candidates.md` as `sdk-candidates-wNNN.md`.

### 2. Review (`/gh-review --auto`)

a. Fetch open issues **excluding `deferred`**. If none → go to the stop check.
b. Triage as `/gh-review` Phase 1 does.
c. Take the recommended ruling for every `needs_decision` / `intent_change` / `conflict`
   item — the option you would mark "(Recommended)". Post it as an issue comment
   **before** the wave runs, starting with `**Ruling (auto, /sdk-autoloop):**`. Then:
   - fix is clear → it joins the wave;
   - a new feature, a design with no single safe default, or a breaking change to a
     public API → apply the `deferred` label, and say why in the comment;
   - already fixed → close with "Already fixed as of vX.Y.Z (sha)."
d. Write `workspace/todos/active/wNNN-gh-issues.md` (gh-review Phase 3 format), with each
   ruling's comment URL on its todo. Do not ask for confirmation.

### 3. Wave

`Workflow({name:"sdk-wave", args:{"waveFile":"workspace/todos/active/wNNN-gh-issues.md","today":"<YYYY-MM-DD>"}})`.
When it ends, read the journal. Known false alarms: the `testsRed`/`protocolBlocked`
flags often come from early rounds that were fixed later — re-run the tests yourself
before believing them. If the wave did not archive itself, archive by hand (move to
`completed/`, mark items `[x]`, add a `plan.md` row, `rmdir` an empty `active/`).

### 4. Release

a. Commit the wave's changes first (`fix: wNNN GitHub issues (GH-a..GH-b)`).
b. Run the `/sdk-release` gate: full pytest (with a placeholder `.md` in
   `workspace/todos/active/` — see `test_lrn_check_grep_paths_exist`), mypy, the four
   protocol advisors in parallel, and the alphageo boot + OAuth probes.
c. Fix every critical/high the gate finds, in place, and re-run the affected leg. Mediums
   and lows go to `workspace/todos/deferred/wNNN-protocol-medium.md`.
d. Version: minor if any item changes behaviour a client can see; patch otherwise.
   Bump `pyproject.toml` + `uv.lock`, retitle `## [Unreleased]`, commit
   `chore: release vX.Y.Z`, `git tag -a`, `git push origin HEAD --follow-tags`.
   Never force-push.
e. Close each fixed issue: "Fixed in vX.Y.Z (sha7)."
f. Save a `sdk-vX.Y.Z-release-outcomes` memory and index it.

### 5. Stop check

Stop when any of these holds, and write the final report:

| Condition | Report as |
|---|---|
| Done (see Definitions) | finished |
| Cycle cap reached | stopped — cap; list what is still open |
| The number of issues filed did not fall for 2 cycles in a row | stopped — not converging |
| The release gate stays red after 2 fix attempts | stopped — gate red; nothing pushed for this cycle |
| A fix would need files outside `a2a-sdk/` | stopped — out of scope |

Otherwise start the next cycle at step 1.

## Hard limits (never relaxed by auto mode)

- Only modify files inside this repo. Never touch `Development/agents/*`.
- Never read `.env` secrets. Never put a credential value in an issue, comment or commit.
- A ruling is a GitHub comment URL before the wave runs — never only in the wave file.
- Never close an issue that was not fixed in a pushed release or verified already fixed.
- Never remove a `deferred` label the developer applied.

## Final report

Plain language. Per cycle: issues filed, rulings taken (with links), issues deferred,
release version + sha, issues closed. Then: what is still open (deferred only, or why
it stopped), and any gate finding that was deferred rather than fixed.
