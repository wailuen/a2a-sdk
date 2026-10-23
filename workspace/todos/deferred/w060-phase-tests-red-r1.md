# w060 — phase — tests RED (round 1)

- Wave: w060
- Scope: phase
- Date: 2026-10-23
- Round: 1
- Reason: test suite RED after the fix attempt; blocking findings below are unresolved.

## Instruction

Fix failing tests and remaining findings, then re-run /wave w060.

SHARED WORKING TREE RULE: other agents have uncommitted work in this tree. NEVER run
`git stash`, `git reset`, `git checkout -- <path>`, `git restore`, `git clean` or
`git checkout .`. Edit files in place. Use `git show` / `git diff` to inspect old content.

## Blocking findings

### RT-001 (high) — CHANGELOG.md:16 — sdkCandidate: true
- Quote: GH-223 CHANGELOG entry citing "Template commit pushed to wailuen/a2a-agent-template: 2ccf3acbe34b979351465994258ff6e896664b57".
- Description: [SDK] Template commit 2ccf3ac is stale. `template/.claude/workflows/wave-cycle.js` has uncommitted, unpushed fixes (`git -C template status` shows ` M .claude/workflows/wave-cycle.js`), so the pushed template ships the weaker FILE_SDK_ISSUES_PY (no JWT/Google/Slack/Stripe/GitLab/`password=` redaction, LONG threshold 40, no label fallback). `tests/test_wave_scope_extraction.py::test_gh164_template_mirror_is_committed_and_pushed` FAILS. The commit is only on origin/feat/gh210-acceptance-turn-helper, not origin/main (LRN-452: `git -C template diff --stat origin/main -- .claude/workflows/wave-cycle.js` is non-empty).
- Fix: Commit and push current `template/.claude/workflows/wave-cycle.js`, get it merged to template origin/main (or record the open template PR as the delivery), and replace the SHA in the GH-223 CHANGELOG entry with the commit holding the final byte-identical copy. Re-run `tests/test_wave_scope_extraction.py` and `tests/test_workflow_sync.py`.
- Codify: A template SHA recorded in the CHANGELOG must be re-taken after the last redteam fix round; any later harness edit re-dirties the mirror and silently ships the older, weaker copy.

### RT-002 (high) — docs/tools.md:75 — sdkCandidate: true
- Quote: "Do not put `anyOf`, `oneOf` or `allOf` at the top level of the input schema"
- Description: [SDK] GH-221 part 5 contradicts the maintainer ruling and the todo AC. The ruling says document adding `anyOf: [{required:[A]},{required:[B]}]` via `model_config = {"json_schema_extra": ...}`; the landed docs forbid it and teach a model_validator pattern, with no recorded re-ruling on issue 221.
- Fix: Either follow the ruling (show the json_schema_extra anyOf example in docs/tools.md), or post the Anthropic top-level-anyOf rejection evidence on issue 221, obtain a new maintainer ruling comment, and cite that URL in docs/tools.md, the GH-221 CHANGELOG bullet and the todo AC. Do not ship the contradiction unratified.
- Codify: When a ruling's instruction looks technically wrong, escalate for a new ruling URL before landing a contrary change; never silently invert a ruled AC.

### RT-003 (high) — workspace/todos/active/w060-gh-issues.md:49 — sdkCandidate: true
- Quote: "  - Creates: (modifies `docs/deployment.md`, `docs/security.md` (trusted-proxy paragraph), `CHANGELOG.md`)"
- Description: [SDK] LRN-441/LRN-446 check fails: `tests/test_changelog_gh143_gh144_wire_changes.py` was modified (AGENT_SDK_TRUSTED_PROXIES dropped from `_GRANDFATHERED_ALIASES`, forced by the GH-218 CHANGELOG line naming it) but appears in no todo Creates/Modifies line, and the GH-218 CHANGELOG bullet does not name it.
- Fix: Add `tests/test_changelog_gh143_gh144_wire_changes.py` (_GRANDFATHERED_ALIASES ratchet) to the GH-218 Creates line, and add a `Tests:` clause naming it to the GH-218 CHANGELOG bullet.
- Codify: A CHANGELOG line that names a grandfathered settings alias trips the alias ratchet test; plan that test file into the same todo's Creates line.
