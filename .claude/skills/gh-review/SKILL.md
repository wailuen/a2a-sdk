---
name: gh-review
category: core
description: "Pull open GitHub issues on wailuen/a2a-sdk, analyze each against the SDK codebase, group compatible work into a wave, and /wave it — or surface conflicts for the developer to resolve first."
---

# /gh-review — GitHub Issue Triage and Wave Execution

Fetches all open issues on `wailuen/a2a-sdk`, analyzes them against the current
codebase and in-progress waves, groups actionable work into a wave file, and
executes it via `/wave`. Issues that conflict with in-progress work, require a
spec decision, or would change SDK intent are surfaced for the developer first.

## Usage

```
/gh-review
/gh-review --dry-run   (analyze + plan only; do not execute the wave)
/gh-review --skip <N,M,...>   (exclude specific issue numbers from this run)
```

## Steps

### Phase 0 — Fetch open issues

1. Pull all open issues from the SDK repo:
   ```bash
   gh issue list --repo wailuen/a2a-sdk --state open --limit 50 \
     --json number,title,body,labels,createdAt
   ```
   If zero open issues: report "No open issues. Nothing to do." and stop.

2. Print a numbered list of the fetched issues (number, title, label if any).

### Phase 1 — Triage each issue (parallel analysis agents)

Dispatch one analysis agent per issue simultaneously. Each agent:

1. Reads the issue title + body.
2. Reads the relevant SDK source file(s) implicated by the title
   (e.g., `agent_sdk/routes/mcp.py` for an MCP issue, `agent_sdk/auth/` for auth).
3. Reads `workspace/todos/active/` to check for in-progress waves touching the
   same files.
4. Reads `workspace/todos/completed/` and `workspace/todos/plan.md` to check if
   the issue is already fixed in landed code.
5. Returns a structured triage record:

```json
{
  "number": <int>,
  "title": "<str>",
  "status": "actionable" | "already_fixed" | "conflict" | "intent_change" | "needs_decision",
  "severity": "critical" | "high" | "medium" | "low",
  "component": "<sdk component label>",
  "files": ["<file:line>", ...],
  "summary": "<one paragraph: what the fix requires>",
  "conflict_reason": "<str or null>",
  "wave_todos": ["<specific, verifiable work item>", ...]
}
```

**Status definitions:**

| Status | Meaning |
|--------|---------|
| `actionable` | Fix is clear, files are known, no conflict with in-progress waves |
| `already_fixed` | The reported behavior no longer exists in current code (issue wasn't closed) |
| `conflict` | The required files are being modified by an in-progress wave |
| `intent_change` | The fix would alter an SDK design decision (needs developer judgment) |
| `needs_decision` | The correct behavior is ambiguous — the issue needs clarification |

### Phase 2 — Synthesize: sort by status and severity

Group triage records:

1. **`already_fixed`**: list them, then run:
   ```bash
   gh issue close <N> --comment "Already fixed as of v<current-version>."
   ```
   for each. No wave needed.

2. **`conflict` / `intent_change` / `needs_decision`**: surface these to the
   developer with the reason. Do NOT include in the wave. Ask if any should be
   overridden or deferred.

3. **`actionable`**: group all actionable issues into wave todos, sorted by
   severity (critical → high → medium → low).

If there are no actionable issues after filtering, report the summary and stop.

### Phase 3 — Build the wave file

4. Determine the next wave number. The local `workspace/todos/` tree alone is
   not authoritative — a branch that diverged from `main` (own commits ahead,
   unmerged commits behind) can carry its own archived wave with the SAME
   number for UNRELATED work (confirmed collision: local `w039` and
   `origin/main`'s `w039` resolve different GitHub issues entirely). Scan every
   fetched ref, not just the local directory listing:
   ```bash
   git fetch origin --quiet 2>/dev/null
   { ls workspace/todos/active/ workspace/todos/completed/ workspace/todos/archive/ \
       workspace/todos/deferred/ 2>/dev/null | grep -oE 'w[0-9]+';
     git log --all -E --grep='archive w[0-9]+' --format=%s 2>/dev/null \
       | grep -oE 'w[0-9]+'; } \
     | sed 's/^w//' | sort -n | tail -1
   ```
   Increment the resulting number (zero-padded to at least 3 digits, matching
   existing convention) to get `w<NNN>`. If this run's own wave file will be
   named the same as one already found on another ref, bump again — the goal
   is a number unused anywhere in `git log --all`, not just locally.

5. Write `workspace/todos/active/w<NNN>-gh-issues.md`:

```markdown
# w<NNN> — GitHub issues <first#>–<last#>

Sourced from open issues on wailuen/a2a-sdk. All items are independent.
Run in parallel (group:G).
Target: <next patch version>.

---

<for each actionable issue, one todo block:>

- [ ] `GH-<N>` <title> ‖ group:G
  - Creates: (modifies `<file>`)
  - Reads: `<file>`
  - Severity: <severity>
  - Root cause: <summary from triage>
  - AC: <one acceptance criterion per wave_todo item>
  - GH: https://github.com/wailuen/a2a-sdk/issues/<N>
```

6. Show the wave file to the developer and confirm:
   "Wave w<NNN> with <N> items ready. Execute now? [yes / dry-run / edit / cancel]"

   - `dry-run` or `--dry-run` flag: print the wave file and stop.
   - `edit`: open the wave file for manual adjustment, then re-confirm.
   - `cancel`: stop cleanly.
   - `yes`: proceed to Phase 4.

### Phase 4 — Execute the wave

7. Invoke the wave skill:
   ```
   /wave w<NNN>
   ```
   This runs the full wave-cycle: implement → redteam → protocol audit → codify → archive.

8. After the wave completes, stage all changes but **do not commit or push**:
   ```bash
   git add -A
   ```
   `/sdk-release` is the only path that commits and pushes. This ensures the full
   test gate (unit + mypy + static conformance) runs before anything ships.

9. Report and hand off:

   ```
   Wave w<NNN> complete — changes staged, not committed.

   Run `/sdk-release <next-patch-version>` to:
     • run the full sdk-test gate (unit + mypy + static conformance)
     • write CHANGELOG.md
     • commit, tag, and push

   After the release ships, close the resolved issues:
     gh issue close <N1> --repo wailuen/a2a-sdk \
       --comment "Fixed in v<version> (<sha7>)."
     ...
   ```

   List every GH issue number that was fixed in the wave so the developer
   can paste the close commands after `/sdk-release` confirms success.

---

## Conflict and intent-change examples

These are NOT actionable without developer input:

| Situation | Status |
|-----------|--------|
| Issue asks to change `_DEFAULT_PROTOCOL_VERSION` but `w006` is modifying `routes/mcp.py` | `conflict` |
| Issue asks to remove the admin console entirely | `intent_change` |
| Issue proposes a new transport (gRPC) not in the current SDK roadmap | `intent_change` |
| Issue title is "question: how do I..." — not a bug report | `needs_decision` |
| Issue body is too vague to identify root cause or affected file | `needs_decision` |

## Rules

- **Never auto-close an issue** without confirming it is already fixed in landed code
  (Phase 2 — `already_fixed` path).
- **Never execute the wave** without developer confirmation (Phase 3 step 6).
- **Never include `intent_change` or `needs_decision` issues in the wave** — surface
  them for the developer to resolve. They may become a separate wave after a decision.
- **One wave file per `/gh-review` run.** If a second run is needed (e.g., after
  resolving a conflict), it creates the next `w<NNN+1>` file.
- **Respect the scope boundary.** Only fixes inside `agent_sdk/`, `harness/`, or
  `template/` are in scope. Issues about downstream agent code are misrouted — close
  with a comment directing to the agent's own issue tracker.
- **Never commit or push in Phase 4.** `/sdk-release` is the only path that ships
  code. Phase 4 stages changes and hands off — it never runs `git commit`, `git push`,
  or `python3 -m agent_sdk bump-patch`. The test gate in `/sdk-release` must run
  before anything reaches `origin/main`.
- **Never close GH issues in Phase 4.** Issues are closed after `/sdk-release`
  confirms a successful push, not before. Phase 4 surfaces the close commands for
  the developer to run post-release.
