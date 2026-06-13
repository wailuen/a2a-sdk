---
name: upgrade
category: core
description: "Bump the agent-sdk pin in pyproject.toml to the latest commit SHA, reinstall, run /agent-verify, and sync harness skill files — showing a diff per changed file and flagging local modifications before overwriting anything."
---

# /upgrade — SDK version upgrade

Safely move this agent to a newer version of `agent-sdk`: read the current pin,
fetch the latest SHA, show what changed, update the pin, reinstall, verify, and
sync harness files in `.claude/` — showing every diff before writing anything.

## Usage

```
/upgrade [--sha <sha>] [--dry-run]
```

- `(no args)` — upgrade to the latest commit on the SDK remote's default branch
- `--sha <sha>` — pin to a specific SHA instead of latest
- `--dry-run` — show changelog + harness diff preview without writing anything
- `--skip-harness` — skip step 10 (harness sync); only bump the pip package

## Steps

1. **Read current pin.**
   Read `pyproject.toml`. Find the `agent-sdk @ git+...@<SHA>` dependency line.
   Extract: `current_sha` (40-char hex), `current_tag` (from the comment line above
   if present), and `sdk_git_url` (the scheme-less host/path after `git+ssh://` or
   `git+https://`).
   If the line is absent, stop: this agent is not on `agent-sdk`.

2. **Resolve target SHA.**
   - If `--sha` given: use it verbatim.
   - Otherwise: `git ls-remote <full_url> HEAD` to get the latest SHA without a
     local clone. Full URL = `git+ssh://<sdk_git_url>` or `git+https://...`.
   If the remote is unreachable with an SSH error, emit: "SSH access to
   `<sdk_git_url>` failed. Ensure the deploy or personal key is loaded:
   `ssh-add ~/.ssh/id_ed25519`. For CI, ensure the key is in `SSH_AUTH_SOCK`."
   Stop on any access failure.
   **Fork warning:** if `sdk_git_url` does not match the canonical SDK URL
   (`github.com/wailuen/a2a-sdk` or similar), emit: "This agent is pinned to a
   fork (`<url>`). Upgrading to the fork's latest — not the canonical SDK release.
   Verify this is intentional before proceeding."

3. **Early exit if already current.**
   If `target_sha == current_sha`: report "already at latest (`<sha7>`)" and stop.

4. **Show changelog.**
   Invoke `/changelog <current_sha> <target_sha> <sdk_git_url>`.
   Display the result before making any changes.
   If `/changelog` fails (git clone unreachable, SSH error), warn and ask:
   "Cannot show changelog — git access failed. Proceed without reviewing changes,
   or abort?" Do not proceed silently without the changelog.
   If `--dry-run`: do NOT stop here — continue to Phase 8 (step 10) in preview
   mode. `--dry-run` exits after the Phase 8 classification report (step 10d),
   having shown both the changelog and the harness diff without writing anything.

5. **Confirm before writing** (unless `--dry-run`).
   Echo: "Upgrading `agent-sdk` from `<current_sha7>` → `<target_sha7>`. Proceed?"
   Wait for user confirmation. On cancel, stop cleanly.

6. **Update `pyproject.toml`.**
   Replace the SHA in the dependency line (leave the comment line's tag as-is or
   update it if the changelog surfaces a tag for the new commit).
   If HTTPS transport is in use, ensure the scheme matches.

7. **Reinstall.**
   Check whether the SDK dependency line reads `agent-sdk[obo] @` (i.e. `[obo]`
   between the package name and the `@`). If so, use `".[obo]"`, otherwise `".[dev]"`.
   `VIRTUAL_ENV=.venv uv pip install -e ".[dev or obo]"`
   If install fails:
   - Revert `pyproject.toml` to the previous SHA.
   - Re-run `VIRTUAL_ENV=.venv uv pip install -e ".[dev]"` against the reverted file
     to restore the venv to the known-good state.
   - If the rollback reinstall also fails, emit a Critical warning: "The venv is in
     an unknown state — advise the user to delete `.venv/` and reinstall from the
     reverted `pyproject.toml`." Stop.

8. **Run tests.**
   `pytest -q tests/` — confirm green baseline before declaring success.
   If tests fail, report which tests broke and ask the user whether to proceed to
   `/agent-verify` or to stop for investigation.

9. **Run `/agent-verify`.**
   The conformance gate catches any protocol-surface breaks the new SDK introduced.
   Surface the report verbatim.

10. **Sync harness files** (skip with `--skip-harness`).

    If `--skip-harness` is set, skip to step 11 and note "Harness sync skipped
    (--skip-harness)" in the report.

    The harness skills, agents, workflow, and reference files in `.claude/` were
    seeded from `harness/` at some prior SDK SHA. This phase brings them up to
    date with `target_sha` — while respecting any local modifications the
    developer made.

    **10a. Resolve the seeded SHA (the base for conflict detection).**
    Read `.claude/.harness-manifest.json`. This file is written by the SDK
    provisioning tool at first seed and updated by `/upgrade` after each successful sync. It maps
    every seeded file to the SDK SHA it was seeded from:
    ```json
    {
      "sdk_sha": "<sha-at-seed-time>",
      "files": {
        ".claude/skills/redteam/SKILL.md": "<sha>",
        ".claude/workflows/wave-cycle.js": "<sha>",
        ...
      }
    }
    ```
    Use `manifest.files[file]` as the per-file `seed_sha`. If the manifest is
    absent (agent predates this feature), fall back to `current_sha` as the base
    for all files and emit a one-time warning:
    "No harness manifest found — using `<current_sha7>` as seed base. Conflict
    classification may be inaccurate if this agent was created at an older SDK
    version."

    **10b. Resolve the SDK repo.**
    Check if the SDK repo is available as a local sibling (same detection as
    `/changelog` step 1). If not, clone it. For small harness sets (< 30 files),
    a shallow full clone at `target_sha` is faster than blobless (avoids per-file
    lazy-fetch round-trips):
    ```bash
    git clone --depth=1 <sdk_url> /tmp/sdk-harness-sync
    git -C /tmp/sdk-harness-sync fetch --depth=1 origin <target_sha>
    git -C /tmp/sdk-harness-sync checkout <target_sha>
    ```
    Clean up the clone when done.

    **10c. Build the file list** from `target_sha` AND from each file's `seed_sha`
    (to detect deletions).
    Tracked harness paths (SDK root → agent `.claude/`):
    ```
    harness/skills/          → .claude/skills/
    harness/agents/          → .claude/agents/
    harness/workflows/       → .claude/workflows/
    harness/reference/       → .claude/reference/
    harness/settings.json    → .claude/settings.json
    ```
    Enumerate files at `target_sha`:
    ```bash
    git -C <sdk-path> ls-tree -r --name-only <target_sha> -- \
      harness/skills/ harness/agents/ harness/workflows/ \
      harness/reference/ harness/settings.json
    ```
    Also enumerate files at `seed_sha` (or `current_sha` fallback) to find
    any that existed then but are absent now.

    To read a file at a given SHA:
    ```bash
    git -C <sdk-path> show <sha>:harness/<relative-path>
    ```

    **10d. Classify each file** into one of five states:

    | State | Condition | Action |
    |-------|-----------|--------|
    | **Up to date** | `.claude/file` == `harness/file` at `target_sha` | Skip silently |
    | **Clean update** | `.claude/file` == `harness/file` at `seed_sha` AND differs at `target_sha` | Developer never modified — safe to update |
    | **Local conflict** | `.claude/file` != `harness/file` at `seed_sha` AND `.claude/file` != `harness/file` at `target_sha` | Developer customised — show 3-way diff, require per-file decision |
    | **New file** | Exists at `target_sha` but not in `.claude/` | New skill/agent/reference — offer to add |
    | **Removed in SDK** | Exists in `.claude/` and at `seed_sha` but absent at `target_sha` | SDK deleted this file — offer to remove |

    **10e. Report the classification before writing anything:**
    ```
    Harness sync — <seed_sha7> → <target_sha7>
    Clean updates:    <N>  (SDK changed, you didn't — safe to apply)
    Local conflicts:  <M>  (you modified these — needs review)
    New files:        <K>  (added by this SDK version)
    Removed in SDK:   <J>  (SDK deleted these)
    Up to date:       <I>

    Clean updates (optional diff preview, then batch confirm):
      .claude/workflows/wave-cycle.js          [d = show diff]
      .claude/agents/core/redteam.md           [d = show diff]
    → Apply all N clean updates? [y / n / s = select per file]

    Local conflicts (mandatory 3-way diff, per-file decision):
      .claude/skills/redteam/SKILL.md          [a = accept SDK / k = keep yours / v = view diff]
      .claude/settings.json                    [a = accept SDK / k = keep yours / v = view diff]

    New files:
      .claude/skills/sdk-issue/SKILL.md        [y = add / n = skip]

    Removed in SDK:
      .claude/skills/old-thing/SKILL.md        [y = remove / n = keep]
    ```

    For clean updates:
    - `d` shows `git diff --no-index <seed_version> <target_version>` for that file.
    - `y` applies all; `n` skips all; `s` prompts per file individually.

    For local conflicts (mandatory review before any write):
    - `v` shows the 3-way diff: Left = SDK at `target_sha`, Base = SDK at `seed_sha`,
      Right = your `.claude/file`.
    - `a` overwrites with the SDK version. `k` keeps yours. Repeat until all
      conflicts have an explicit decision.
    Never silently resolve a conflict.

    For removed-in-SDK files: always require explicit `y` before deleting.
    Never auto-delete, even if the file is unmodified.

    If `--dry-run`: stop here — do not write, do not apply. This is the single
    exit point for `--dry-run` (covers both changelog and harness preview).

    **10f. Apply the accepted changes:**
    - Clean updates (y or per-file y): copy `harness/file` at `target_sha` into
      `.claude/file`.
    - New files (y): copy into `.claude/`.
    - Removed-in-SDK (y): delete from `.claude/`.
    - Conflicts accepted (a): overwrite `.claude/file` with SDK version.
    - Skipped/kept files: leave untouched.

    **10g. Update the harness manifest.**
    Rewrite `.claude/.harness-manifest.json` to record `target_sha` as the new
    `sdk_sha`, and update each applied file's SHA to `target_sha`. Leave skipped
    or kept files at their previous SHA so future upgrades can still detect the
    base correctly.

11. **Report.**

```
## SDK upgrade — <agent-name>
Previous:  <current_sha7>  (<current_tag or "no tag">)
New:       <target_sha7>   (<new_tag or "no tag">)
Tests:     <N> passed / <M> failed
Verify:    PASS | FAIL | SKIPPED (error: …)
Harness:   <N> updated  <M> conflicts (skipped/accepted)  <K> new  <J> removed
           Kept (your version): <list of skipped conflict files>
Manifest:  updated → .claude/.harness-manifest.json
Next:      review any kept conflicts manually; commit when satisfied
```

## Rules

- **Never widen security invariants** during an upgrade — if `/agent-verify` finds
  a new SI violation introduced by the SDK change, stop and report it rather than
  suppressing the finding.
- **No commit is made by this skill.** The user reviews, then commits.
- If the upgrade surfaces a **breaking change** in the changelog (tagged `BREAKING`),
  emit a prominent warning before the confirm prompt.
- **Never silently overwrite a locally-modified file.** The conflict detection in
  step 10 is mandatory — a local customisation must be shown and confirmed before
  being replaced.
- **`settings.json` conflicts are treated with extra care.** The deny rules in
  `.claude/settings.json` may have been tightened by the developer. Never replace
  a tighter deny list with a looser one without explicit confirmation.
- **Never auto-delete.** Even a file deleted in the SDK must be explicitly confirmed
  before it is removed from `.claude/`.
- **`--dry-run` shows both the changelog (step 4) and harness diff (step 10e) and
  exits at step 10e.** It does not stop at step 4.

## Integration

- Calls `/changelog` (step 4) — requires git access to the SDK repo.
- Calls `/agent-verify` (step 9) — needs `BEDROCK_MODEL_ARN` or equivalent in `.env`.
- Step 10 requires git access to the SDK repo. Use `--skip-harness` if network
  access is unavailable.
- The SDK provisioning tool writes the initial `.claude/.harness-manifest.json` at first seed.
  Agents seeded before this feature existed get a one-time warning in step 10a.
