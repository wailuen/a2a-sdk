---
name: sdk-issue
category: core
description: "File a GitHub issue on wailuen/a2a-sdk for a confirmed SDK-level bug or gap. Classifies the finding first — agent-domain findings are redirected to /codify (LRN record only, no GitHub issue). Never files noise."
---

# /sdk-issue — File an SDK-level GitHub issue

Takes a finding from `/redteam`, `/agent-verify`, `/diagnose`, or a manual
description, classifies whether it is an SDK-level bug or an agent-domain bug,
and files a structured GitHub issue on `wailuen/a2a-sdk` if and only if it is
SDK-level.

**Agent-domain findings stay in the project.** If the finding is in domain code,
adapters, credentials, or agent-specific configuration, this skill declines and
suggests `/codify` to capture it as an LRN record in `workspace/learning/`.

## Usage

```text
/sdk-issue "<finding summary>"
/sdk-issue   (interactive — prompts for description)
```

Examples:
```text
/sdk-issue "agent-verify reports 401 but WWW-Authenticate header is present and correct"
/sdk-issue "wave-cycle.js codify phase emits duplicate LRN IDs when two waves run concurrently"
/sdk-issue "MCP /token endpoint returns 500 when DCR client_id has a hyphen"
```

## Steps

### Phase 0 — Collect the finding

1. Read `$ARGUMENTS`. If empty, ask:
   "Describe the finding — what broke, what you expected, what actually happened."

2. Also read context if available:
   - Last `/redteam` or `/agent-verify` report in the session
   - Any LRN file path the user references
   - The active wave file (`workspace/todos/active/`)

### Phase 1 — Classify: SDK or agent-domain?

3. Classify the finding into one of:

   **SDK-level** (file as GitHub issue):
   - Bug in a protocol surface: A2A, AG-UI, A2UI, MCP, OAuth (wrong HTTP status,
     wrong header, wrong shape, wrong error code, streaming malfunction)
   - Bug in SDK internals: `build_app()`, `Agent`, `ToolSet`, `SourceAdapter` base
     class, credential store, agentic loop, rate limiter, admin console
   - Harness bug: incorrect step in a SKILL.md, wrong agent instruction,
     wave-cycle.js logic error, LRN schema issue
   - Security invariant gap IN THE SDK: an SI-1…SI-7 violation that the SDK itself
     causes or fails to prevent (not a violation in agent domain code)
   - SDK template bug: placeholder substitution error, missing file, wrong pip
     dependency format in `template/`
   - `/agent-verify` or `/sdk-test` false positive/negative

   **Agent-domain** (redirect to `/codify`):
   - Bug in `src/tools/`, `src/sources/`, `src/config.py`, `src/persona.py`
   - Credential configuration or seeding error
   - Domain-specific test failure
   - Agent-level SI violation (domain code broke an invariant — fix the code, don't
     file it against the SDK)
   - Deployment configuration for a specific agent

4. State the classification explicitly:
   "Classification: **SDK-level** — `<component>`" or
   "Classification: **Agent-domain** — redirecting to `/codify`."

   If agent-domain: stop here and say:
   "This is an agent-domain finding — it belongs in your project's LRN records,
   not a GitHub issue. Run `/codify <finding-summary>` to capture it."

### Phase 2 — Enrich the finding

5. Identify the **component** from the finding:

   | Component label | Area |
   |----------------|------|
   | `protocol/a2a` | A2A v0.3.0 surfaces |
   | `protocol/ag-ui` | AG-UI surfaces |
   | `protocol/a2ui` | A2UI surfaces |
   | `protocol/mcp` | MCP surfaces |
   | `protocol/oauth` | OAuth 2.1 chain |
   | `sdk/build` | `build_app()`, `Agent`, `ToolSet` wiring |
   | `sdk/credentials` | Credential store, `CredentialField` |
   | `sdk/loop` | Agentic loop, tool tiers, interrupts |
   | `sdk/console` | Admin + test console |
   | `harness/skill` | A SKILL.md step or instruction |
   | `harness/agent` | An agent markdown file |
   | `harness/workflow` | `wave-cycle.js` |
   | `harness/template` | `template/` scaffold files |
   | `security` | SI violation in the SDK itself |

   *If a finding spans both `security` and a `protocol/*` label (for example, an
   OAuth endpoint that leaks a token), prefer `protocol/<surface>`. Use `security`
   only for SI violations the SDK itself causes — not protocol-surface deviations.*

6. Determine **severity**:
   - Critical — data loss, secret exposure, auth bypass, agent crash on boot
   - High — protocol non-conformance, broken skill, wrong LRN output
   - Medium — misleading output, poor error message, missing fallback
   - Low — cosmetic, doc gap, polish

7. Identify the **SDK version** (SHA):
   Read `pyproject.toml` in the current repo. Extract the `agent-sdk @` SHA7.
   If in the SDK repo itself, use `git rev-parse --short HEAD`.

### Phase 3 — Check for duplicate

8. Search open issues:
   ```bash
   gh issue list --repo wailuen/a2a-sdk --state open --search "<key terms from finding>" --limit 10
   ```
   If a matching open issue exists, report its URL and number and ask:
   "Issue #<N> looks related — comment on it instead of filing a duplicate?"
   On yes: stop (the user can navigate to the issue). On no: proceed.

### Phase 4 — File the issue

9. Compose the issue body:

```markdown
## Description
<one paragraph: what broke, where, under what conditions>

## Steps to reproduce
1. <step>
2. <step>
3. <observed result>

## Expected behaviour
<what should happen>

## Actual behaviour
<what actually happens>

## Environment
- SDK: `agent-sdk @ <sha7>`
- Agent: <agent-name or "SDK repo">
- Trigger: `/redteam` | `/agent-verify` | `/diagnose` | manual

## Severity
<Critical | High | Medium | Low>

## Component
`<component label from step 5>`
```

10. **Confirm before filing:**
    Show the title and body. Ask: "File this issue on `wailuen/a2a-sdk`? (yes / edit / cancel)"
    - `yes` → proceed
    - `edit` → prompt for what to change, revise, re-confirm
    - `cancel` → stop cleanly

11. File:
    ```bash
    gh issue create \
      --repo wailuen/a2a-sdk \
      --title "<concise title: component: what broke>" \
      --body "<body from step 9>" \
      --label "bug"
    ```
    Report the URL returned by `gh`.

12. **Optionally codify** — if severity is Critical or High, ask:
    "Also capture this as an LRN in `workspace/learning/`? (yes / no)"
    On yes: run `/codify <finding-summary>` — the LRN keeps context in the project
    while the GitHub issue tracks the fix in the SDK.

## Report format

```
## SDK issue filed
Title:     <title>
Component: <component>
Severity:  <severity>
SDK SHA:   <sha7>
Issue:     https://github.com/wailuen/a2a-sdk/issues/<N>
LRN:       captured | skipped
```

## Rules

- **Never file agent-domain bugs as SDK issues.** The classification step is
  mandatory — a wrong classification creates noise in the SDK tracker and
  misattributes blame.
- **Never file without user confirmation** (step 10). This skill creates a
  public (or repo-visible) record — the user must approve the title and body.
- **One issue per finding.** If the finding contains multiple distinct bugs,
  split them: run `/sdk-issue` once per bug.
- **No credentials in issue bodies.** If reproducing the bug requires a
  credential value, describe the credential type only (e.g. "an AlphaGeo API
  key with read access"), never the value.
