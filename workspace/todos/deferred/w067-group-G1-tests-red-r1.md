# w067 — group G1 — tests RED (round 1)

- Wave: w067
- Scope: unit:G1
- Date: 2026-10-25
- Round: 1
- Reason: test suite RED after the fix attempt; blocking findings unresolved.

## Unresolved blocking findings

### RT-001 (high) — CHANGELOG.md:13
- Quote: GH-263 [Unreleased] bullet names `chat.js`, `retry.js`, `a2ui.js` by basename.
- Description: The wave plan requires every changed agent_sdk/ file by repo path (LRN-491/LRN-495). `grep -c agent_sdk/console/static/chat.js` (and a2ui.js, retry.js) over the [Unreleased] block returns 0, failing the LRN-495 Check. New exports `abortableSleep` and `MAX_TOMBSTONES` are not tied to a repo path.
- Fix: Rewrite the file references in the GH-263 bullet as `agent_sdk/console/static/chat.js`, `agent_sdk/console/static/retry.js` (exports `abortableSleep`) and `agent_sdk/console/static/a2ui.js` (exports `MAX_TOMBSTONES`).
- Codify: A CHANGELOG bullet names console static files by full repo path (agent_sdk/console/static/<file>.js), never basename, so the LRN-495 grep over the diff file list passes.
- sdkCandidate: true

### RT-002 (high) — CHANGELOG.md:31
- Quote: `## [Unreleased]`
- Description: CHANGELOG.md has two `## [Unreleased]` headings (lines 7 and 31); `grep -c '^## \[Unreleased\]' CHANGELOG.md` prints 2, failing LRN-494 and the wave rule "keeps exactly one ## [Unreleased] heading". The second block (GH-262/GH-264) duplicates `### Breaking`/`### Fixed`/`### Changed` subheadings, so LRN-491's first-block scan misses half the release notes.
- Fix: Delete the second `## [Unreleased]` heading at line 31 and merge its GH-262 and GH-264 bullets under the matching `### 🔴 Breaking changes`, `### Added`, `### Fixed` and `### Changed` subheadings of the single [Unreleased] block at line 7 (one of each subheading).
- Codify: Before sign-off of any parallel wave, run `grep -c '^## \[Unreleased\]' CHANGELOG.md` and merge duplicates so exactly one Unreleased block with one of each subheading remains.
- sdkCandidate: true

## Instruction

Fix failing tests and remaining findings, then re-run /wave w067.

## Shared working tree rule

Other agents have uncommitted work in this tree. NEVER run `git stash`, `git reset`, `git checkout -- <path>`, `git restore`, `git clean` or `git checkout .`. Edit files in place. Use `git show` / `git diff` to inspect old content.
