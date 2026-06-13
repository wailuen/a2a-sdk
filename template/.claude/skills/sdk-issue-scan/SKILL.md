---
name: sdk-issue-scan
description: "Batch-classify and file GitHub issues for SDK-level findings from a wave, /redteam, or /agent-verify run. Reads from workspace/sdk-candidates.md (written by wave-cycle.js) or from the current session context. Classifies SDK vs agent-domain; files confirmed issues on wailuen/a2a-sdk with one user confirmation per filing. Run after /wave whenever sdk-candidates.md is written, or after any /redteam or /agent-verify that surfaces harness/SDK bugs."
---

# /sdk-issue-scan — batch SDK issue triage and filing

Reads findings from the current wave or session, classifies each as SDK-level vs
agent-domain, and files confirmed SDK issues on `wailuen/a2a-sdk` — one user
confirmation per finding, nothing filed automatically.

This is the batch entry point after `/wave`. The single-finding filing logic is in
`/sdk-issue` — this skill orchestrates it across multiple findings and integrates
with the wave workflow's candidate file.

## Usage

```
/sdk-issue-scan                    — read workspace/sdk-candidates.md (wave output)
/sdk-issue-scan "<description>"    — classify and propose filing one specific finding
/sdk-issue-scan --context          — read findings from current session context only
```

## When to run

| Trigger | When |
|---------|------|
| After `/wave` | Automatically: wave-cycle.js writes `workspace/sdk-candidates.md` when it detects SDK-level findings. Check the Codify phase log. |
| After `/redteam` | If the report contains [SDK-LEVEL] tagged findings. |
| After `/agent-verify` | If the OAuth-chain or stack-check leg surfaces harness or SDK bugs. |
| Manually | Any time you hit a reproducible SDK bug mid-development. |

## Steps

### Phase 0 — Collect findings

1. Determine the source:
   - If `$ARGUMENTS` is a description string → treat it as a single finding (go to Phase 1)
   - If `$ARGUMENTS` is `--context` → read findings from the current session (redteam/verify output)
   - Otherwise: check for `workspace/sdk-candidates.md`; if it exists, read it

2. If `workspace/sdk-candidates.md` exists, parse the candidate list. Each candidate has:
   - Description
   - Severity (critical/high)
   - Component label (e.g. `harness/skill`, `sdk/build`)
   - Rationale (why the wave-cycle classifier flagged it as SDK-level)

3. If `--context` or no candidates file, extract all Critical/High findings from the
   most recent `/redteam` or `/agent-verify` report in the conversation.

4. If no findings are found anywhere, say: "No SDK candidates found. Run `/sdk-issue`
   with a specific description to file a finding manually."

### Phase 1 — Verify classification (fail closed)

5. For each candidate, confirm it is genuinely SDK-level:

   **SDK-level (file as GitHub issue):**
   - Harness: wrong step in a SKILL.md, wrong agent instruction, wave-cycle.js logic error
   - SDK internals: `build_app()`, `Agent`, `ToolSet`, `SourceAdapter` base class,
     credential store, agentic loop, admin console
   - Protocol surface: wrong HTTP status, missing handler, wrong response shape in
     `src/routes/` (if caused by SDK behavior, not agent-specific code)
   - Template scaffold: wrong pattern in `template/`, wrong SDK API in skill examples
   - Security: an SI violation that the SDK itself causes or fails to prevent

   **Agent-domain (skip, suggest `/codify`):**
   - `src/tools/`, `src/sources/`, `src/config.py`, domain test failures
   - Credential configuration, agent-specific auth setup
   - An SI violation in the agent's own code (fix the code, not the SDK)

6. Show the classification table before filing:

   ```
   # SDK Scan — <wave-id or session>

   Found N candidates. Classification:

   | # | Description (truncated)         | Classification  | Component       |
   |---|---------------------------------|-----------------|-----------------|
   | 1 | wave-cycle MCP not dispatched   | SDK-level ✓     | harness/workflow |
   | 2 | src/tools/fetch.py auth bug     | Agent-domain ✗  | —               |
   ```

   M of N will be proposed for filing.

### Phase 2 — File SDK issues (one confirmation per finding)

7. For each confirmed SDK-level finding, in order:

   **a. Check for duplicates:**
   ```bash
   gh issue list --repo wailuen/a2a-sdk --state open \
     --search "<key terms from description>" --limit 5
   ```
   If a matching open issue exists, show its URL and ask:
   "Issue #N looks related — comment on it instead? (comment / new / skip)"

   **b. Compose the issue:**
   ```
   Title: <component>: <concise description of what broke>

   ## Description
   <what broke, where, under what conditions — 1 paragraph>

   ## Steps to reproduce
   1. <step>
   2. <observed result>

   ## Expected behaviour
   <what should happen>

   ## Actual behaviour
   <what actually happens>

   ## Environment
   - SDK: agent-sdk @ <sha7 from pyproject.toml or git rev-parse --short HEAD>
   - Agent: <agent-name or "template">
   - Trigger: /wave | /redteam | /agent-verify | manual

   ## Severity
   <Critical | High>

   ## Component
   `<component label>`
   ```

   **c. Confirm before filing:**
   Show the title + body preview. Ask:
   "File this issue on `wailuen/a2a-sdk`? (yes / edit / skip / cancel-all)"
   - `yes` → file with `gh issue create`; report URL
   - `edit` → prompt for what to change, revise, re-confirm
   - `skip` → move to the next finding
   - `cancel-all` → stop all remaining filings

   **d. File:**
   ```bash
   gh issue create \
     --repo wailuen/a2a-sdk \
     --title "<title>" \
     --body "<body>" \
     --label "bug"
   ```

### Phase 3 — Report and clean up

8. Show the summary:
   ```
   ## SDK issue scan complete

   Filed:        N — <URLs>
   Skipped:      M (user skipped or duplicate)
   Agent-domain: K (not filed — fix in agent code; run /codify if instructive)

   Candidates file: workspace/sdk-candidates.md — archived to workspace/sdk-candidates-<wave-id>.md
   ```

9. Archive the candidates file (rename to `workspace/sdk-candidates-<wave-id>.md`) so
   a subsequent `/sdk-issue-scan` doesn't re-read stale candidates. If wave ID is not
   known, archive as `sdk-candidates-<today>.md`.

10. **Optional codify**: for any Critical/High finding the user skipped, ask once:
    "Capture any skipped SDK findings as LRNs? (yes / no)"
    On yes: `/codify <finding-summary>` for each.

## Rules

- **Never file without per-finding confirmation.** Every issue requires an explicit "yes"
  at step 7c.
- **Never file agent-domain findings as SDK issues.** Classification is mandatory.
- **No credentials in issue bodies.** Describe the credential type, never the value.
- **Deduplicate.** Check `gh issue list` before composing the body (step 7a).
- **One issue per distinct root cause.** If two candidates trace to the same defect,
  merge them into one issue — say "This also covers candidate N."
