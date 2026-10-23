# w059 — group G7 — tests RED (round 1)

- Wave: w059
- Scope: unit:G7
- Date: 2026-10-22
- Round: 1
- Reason: test suite RED after the fix attempt; blocking findings unresolved.

## Unresolved blocking findings

### RT-001 (high) — template/.claude/skills/acceptance/SKILL.md
- sdkCandidate: true
- Description: [SDK] The Phase 1.5 hunk is committed (fd21b8e) and pushed only to the feature branch origin/feat/gh210-acceptance-turn-helper, which has no PR. Remote main is still at 02555da, and `git -C template diff origin/main --stat -- .claude/skills/acceptance/SKILL.md` shows +67/-1. Downstream agents that sync the template from main never receive the gate. This fails the LRN-335 Check (template clean against origin/main; severity high) and the LRN-314 intent.
- Fix: Open a PR on wailuen/a2a-agent-template from feat/gh210-acceptance-turn-helper to main, or push to main as the delivery step. Do not mark GH-209 done until `git -C template diff origin/main -- .claude/skills/acceptance/SKILL.md` is empty. Add an archive-gate check for this diff.
- Codify: Pushing the template mirror to a feature branch with no PR is not delivery. The gate is a diff against origin/main (LRN-335), not 'git push succeeded'.

## Instruction

Fix failing tests and remaining findings, then re-run /wave w059.

## Shared working tree rule

Other agents have uncommitted work in this tree. NEVER run `git stash`, `git reset`,
`git checkout -- <path>`, `git restore`, `git clean` or `git checkout .`. Edit files in
place. To inspect old content use `git show` / `git diff`.
