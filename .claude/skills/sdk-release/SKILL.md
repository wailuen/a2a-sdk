---
name: sdk-release
category: sdk-dev
description: "Cut a release tag for agent-sdk: confirm /sdk-test is green, bump the version in pyproject.toml, write CHANGELOG.md, commit, tag, and push to the remote. Only runs when all tests pass."
---

# /sdk-release — Cut a release

Runs the full release ceremony for `agent-sdk`: version bump, changelog,
commit, tag, push. Never runs without a clean `/sdk-test`.

## Usage

```
/sdk-release <semver>
```

Example: `/sdk-release 1.3.0`

- `semver` must be a valid SemVer string (`MAJOR.MINOR.PATCH[-pre]`).
- Must be higher than the current version in `pyproject.toml`.

## Steps

### Phase 0 — Pre-flight

1. Read `pyproject.toml`. Extract `version`. Confirm the requested version is
   strictly higher. On failure: "Current version is `<current>`; `<requested>`
   is not a valid bump." Stop.

2. **Require a clean `/sdk-test`.** Run `/sdk-test` in full (all three legs).
   If any leg is RED, stop with: "Release blocked: `/sdk-test` failed. Fix before
   tagging."

3. Check the git working tree is clean:
   ```bash
   git status --short
   ```
   If there are uncommitted changes, stop: "Uncommitted changes present. Commit or
   stash before releasing."

4. Capture the current branch name:
   ```bash
   git rev-parse --abbrev-ref HEAD
   ```
   Warn if not `main` or `release/*`, but do not stop — the user may be releasing
   from a named branch intentionally. This branch name is used in step 11's push.

### Phase 1 — Version bump

5. Read `pyproject.toml` to identify the build backend from `[build-system] requires`:
   - `hatchling`, `setuptools`, `flit` → canonical version is in `[project] version`.
   - `poetry` → canonical version is in `[tool.poetry] version`.
   Update only the canonical field. Verify with:
   ```bash
   grep -n 'version' pyproject.toml
   ```
   Confirm exactly one version line changed and no stray fields were modified.

### Phase 2 — Changelog

6. Generate the changelog entry. Collect all commits since the last tag:
   ```bash
   git describe --tags --abbrev=0 2>/dev/null || echo "FIRST_RELEASE"
   ```
   - If a tag exists: `git log <last-tag>..HEAD --pretty=format:"%H %s" --reverse`
   - If no tag (first release): `git log --pretty=format:"%H %s" --reverse`
     and note in the changelog header: "Initial release — full history follows."
   Categorise them (same rules as `/changelog`). Insert a new `## [<semver>] — <date>`
   section at the top of `CHANGELOG.md` (below the `# Changelog` header), before
   the previous `## [...]` entry.

   Format:
   ```markdown
   ## [1.3.0] — 2026-06-12

   ### Breaking changes
   - <sha7> <subject>

   ### Protocol surface changes
   - ...

   ### Features
   - ...

   ### Fixes
   - ...
   ```
   Omit empty sections.

### Phase 3 — Commit + tag + push

7. After `/sdk-test` completes (step 2), re-run `git status --short` to confirm
   the test run left no uncommitted artifacts. If it did, ensure they are covered
   by `.gitignore` — otherwise `git add` below will not pick them up, but the user
   should be aware.

8. Stage the two files:
   ```bash
   git add pyproject.toml CHANGELOG.md
   ```

9. Commit:
   ```bash
   git commit -m "chore: release v<semver>"
   ```

10. Tag:
    ```bash
    git tag -a "v<semver>" -m "Release v<semver>"
    ```

11. **Confirm before pushing:**
    "About to push commit + tag `v<semver>` from branch `<branch>` to origin. Proceed?"
    Wait for user confirmation. Never force-push.

12. On confirmation, push the current branch (not hardcoded `main`):
    ```bash
    git push origin HEAD --follow-tags
    ```

### Report

```
## Release — v<semver>
Previous:   v<last_tag>
Branch:     <branch>
Tests:      GREEN (full 3-leg pass)
Changelog:  <N commits categorised>
Commit:     <sha7>
Tag:        v<semver>
Pushed:     YES | PENDING USER CONFIRMATION

Next:
  - agents using this SDK can now run /upgrade to get v<semver>
  - post the changelog to the project README / release notes
```

## Rules

- **Never skip `/sdk-test`.** The test gate is the only thing standing between
  a broken SDK and pinned agents that can't upgrade.
- **Never force-push main or a tag.**
- If the user cancels at step 10, the commit and tag exist locally but are not
  pushed. They can push manually or run `/sdk-release` again with the same
  version (step 5 will fail gracefully — bump check catches the already-matching
  version and offers to push the existing tag).
- **Patch releases** (MAJOR.MINOR.PATCH with no change to FR count) are expected
  to have zero BREAKING commits in the changelog. If BREAKING commits exist for a
  patch bump, warn before proceeding.
- **Minor releases** may add features but not remove or narrow existing tool
  contracts. Flag any commits that look like contract narrowing.
