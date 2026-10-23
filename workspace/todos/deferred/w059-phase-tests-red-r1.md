# w059 — phase blocked: tests RED (round 1)

- **Wave:** w059
- **Scope:** phase
- **Date:** 2026-10-22
- **Round:** 1
- **Reason:** test suite RED after the fix attempt; blocking findings unresolved.

## Unresolved blocking findings

### RT-001 — high — `template/.claude/workflows/wave-cycle.js` [SDK candidate]

The template mirror deliverables for GH-208, GH-209, GH-210 and GH-211 are not delivered. template/ is on branch feat/gh210-acceptance-turn-helper (HEAD fd21b8e). That HEAD is not an ancestor of origin/main and also lacks origin/main's GH-211 commit 02555da. The working tree has uncommitted edits to .claude/workflows/wave-cycle.js and acceptance-api.js. template/.claude/agents/core/redteam.md differs from harness/agents/core/redteam.md at line 175 (the stale-rule wording). tests/test_wave_scope_extraction.py::test_gh164_template_mirror_is_committed_and_pushed FAILS. The LRN-335 Check fails because `git -C template status --short` is not empty. The todo ACs say all mirrors are committed and pushed to wailuen/a2a-agent-template as the final step.

- **Fix:** In template/, rebase or merge the feature branch onto origin/main so it includes 02555da. Sync redteam.md byte-identical to the harness copy, commit the two dirty workflow files, push, and merge the template PR into main. Then re-run test_gh164_template_mirror_is_committed_and_pushed and tests/test_workflow_sync.py.
- **Codify:** A template mirror counts as delivered only when the template HEAD is clean and reachable from origin/main. A pushed feature branch or a byte-identical working copy is not delivery (re-confirms LRN-335).

### RT-002 — high — `CHANGELOG.md` [SDK candidate]

The LRN-433 Check fails. The [Unreleased] section never names these changed agent_sdk files: loop.py, runner.py, a2a.py (where the new public helper cancel_task_record now lives), ag_ui.py and testing/__init__.py. Several statements are also wrong. Line 10 (GH-221) tells clients they 'must send a valid Mcp-Session-Id' on GET /mcp, but no header still returns 200. Line 14 (GH-204) gives the test as tests/test_gh209_testing_mcp.py, but GH-204's test is tests/test_rt003_rt004_mcp_error_mapping.py. The GH-221 entry is filed under 'Breaking changes', while the AC asks for 'Changed'.

- **Fix:** Name every changed agent_sdk file in its entry (GH-220: loop.py, runner.py, ag_ui.py; GH-217: a2a.py with cancel_task_record, ag_ui.py; GH-209/210: testing/__init__.py). Fix the GH-221 migration sentence to say the header is optional and checked only when present. Fix the GH-204 test path. Reconcile the heading with the AC, or record why it moved.
- **Codify:** Run the LRN-433 basename check against CHANGELOG [Unreleased] before a wave's phase redteam closes. Every helper moved into a new module counts as a changed file to name.

## Next step

Fix failing tests and remaining findings, then re-run /wave w059.

Shared working tree rule: other agents have uncommitted work in this tree. Never run `git stash`, `git reset`, `git checkout -- <path>`, `git restore`, `git clean` or `git checkout .`. Edit files in place; use `git show` / `git diff` to inspect old content.
