---
name: upgrade
category: core
description: "Bump the agent-sdk pin in pyproject.toml to the latest commit SHA, reinstall, run /agent-verify, and surface a changelog between the old and new versions."
---

# /upgrade — SDK version upgrade

Safely move this agent to a newer version of `agent-sdk`: read the current pin,
fetch the latest SHA, show what changed, update the pin, reinstall, verify.

## Usage

```
/upgrade [--sha <sha>] [--dry-run]
```

- `(no args)` — upgrade to the latest commit on the SDK remote's default branch
- `--sha <sha>` — pin to a specific SHA instead of latest
- `--dry-run` — show what would change (changelog + diff) without writing anything

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
   If the remote is unreachable, report the error and stop.

3. **Early exit if already current.**
   If `target_sha == current_sha`: report "already at latest (`<sha7>`)" and stop.

4. **Show changelog.**
   Invoke `/changelog <current_sha> <target_sha> <sdk_git_url>`.
   Display the result before making any changes. If `--dry-run`, stop here.

5. **Confirm before writing** (unless `--dry-run`).
   Echo: "Upgrading `agent-sdk` from `<current_sha7>` → `<target_sha7>`. Proceed?"
   Wait for user confirmation. On cancel, stop cleanly.

6. **Update `pyproject.toml`.**
   Replace the SHA in the dependency line (leave the comment line's tag as-is or
   update it if the changelog surfaces a tag for the new commit).
   If HTTPS transport is in use, ensure the scheme matches.

7. **Reinstall.**
   `VIRTUAL_ENV=.venv uv pip install -e ".[dev]"` (or `".[obo]"` if the obo extra
   is present in the current pyproject).
   If install fails, revert `pyproject.toml` and report the error — do NOT leave the
   agent with a mismatched file and a failed install.

8. **Run tests.**
   `pytest -q tests/` — confirm green baseline before declaring success.
   If tests fail, report which tests broke and ask the user whether to proceed to
   `/agent-verify` or to stop for investigation.

9. **Run `/agent-verify`.**
   The conformance gate catches any protocol-surface breaks the new SDK introduced.
   Surface the report verbatim.

10. **Report.**

```
## SDK upgrade — <agent-name>
Previous: <current_sha7>  (<current_tag or "no tag">)
New:      <target_sha7>   (<new_tag or "no tag">)
Tests:    <N> passed / <M> failed
Verify:   PASS | FAIL | SKIPPED (error: …)
Next:     review changelog above; commit when satisfied
```

## Rules

- **Never widen security invariants** during an upgrade — if `/agent-verify` finds
  a new SI violation introduced by the SDK change, stop and report it rather than
  suppressing the finding.
- **No commit is made by this skill.** The user reviews, then commits.
- If the upgrade surfaces a **breaking change** in the changelog (tagged `BREAKING`),
  emit a prominent warning before the confirm prompt.

## Integration

- Calls `/changelog` (step 4) — install or mock this skill before using upgrade.
- Calls `/agent-verify` (step 9) — boot the agent; needs `BEDROCK_MODEL_ARN` or
  equivalent in `.env`.
