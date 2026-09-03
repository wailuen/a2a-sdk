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

2. **Changelog/pyproject agreement guard — run before touching either file.**
   A wave or hand-edit can retitle `CHANGELOG.md`'s newest heading (e.g. to
   record a versioning-discipline finding, as in RT-002) without updating
   `pyproject.toml` to match, leaving the two disagreeing about what the
   *current* release even is. Read `CHANGELOG.md`, find the first `## [X.Y.Z]`
   heading after the `# Changelog` line, and compare it to the `version` read
   in step 1 (the *current* pyproject version, not the requested one). If they
   differ, stop: "CHANGELOG.md's newest heading is `[<changelog-version>]` but
   pyproject.toml declares `<pyproject-version>`. These must already agree
   before a release proceeds — reconcile them by hand (pick the correct number
   and fix whichever file is wrong) and re-run `/sdk-release`." Never resolve
   this by silently picking one side.

3. **Ancestry guard — refuse to bump or tag on a stale or foreign-numbered
   branch.** A version bump is a claim about ancestry, not just a number.
   ```bash
   git fetch origin
   git rev-list --count HEAD..origin/main
   git tag --list 'v*' --merged HEAD
   ```
   - If `HEAD..origin/main` is non-zero, stop: "Branch is `<N>` commits behind
     `origin/main`. Reconcile (rebase or merge) before releasing — a bump from
     here would silently omit everything origin already shipped." Never bump
     `pyproject.toml` to work around this.
   - Find the highest SemVer tag reachable from `HEAD` (`--merged HEAD`) as well
     as the highest tag that exists anywhere in the remote (`git tag --list 'v*'`
     without `--merged`, taken from `origin` after the fetch). If the requested
     version is not strictly greater than *both*, stop: "`<requested>` does not
     exceed `<highest-tag>`, which already exists in this repository's tag
     history. This branch's history does not contain that release — do not
     reuse or leapfrog its number." A branch that has never merged a tag's
     lineage may not claim any version above it, even if that tag is absent
     from `HEAD`'s own ancestry.

4. **Require a clean `/sdk-test`.** Run `/sdk-test` in full (all three legs).
   If any leg is RED, stop with: "Release blocked: `/sdk-test` failed. Fix before
   tagging."

5. Check the git working tree is clean:
   ```bash
   git status --short
   ```
   If there are uncommitted changes, stop: "Uncommitted changes present. Commit or
   stash before releasing."

6. Capture the current branch name:
   ```bash
   git rev-parse --abbrev-ref HEAD
   ```
   Warn if not `main` or `release/*`, but do not stop — the user may be releasing
   from a named branch intentionally. This branch name is used in step 14's push.

### Phase 1 — Version bump

7. Read `pyproject.toml` to identify the build backend from `[build-system] requires`:
   - `hatchling`, `setuptools`, `flit` → canonical version is in `[project] version`.
   - `poetry` → canonical version is in `[tool.poetry] version`.
   Update only the canonical field. Verify with:
   ```bash
   grep -n 'version' pyproject.toml
   ```
   Confirm exactly one version line changed and no stray fields were modified.

### Phase 2 — Changelog

8. Generate the changelog entry. Collect all commits since the last tag:
   ```bash
   git describe --tags --abbrev=0 2>/dev/null || echo "FIRST_RELEASE"
   ```
   - If a tag exists: `git log <last-tag>..HEAD --pretty=format:"%H %s" --reverse`
   - If no tag (first release): `git log --pretty=format:"%H %s" --reverse`
     and note in the changelog header: "Initial release — full history follows."
   Categorise them (same rules as `/changelog`). Insert a new `## [<semver>] — <date>`
   section at the top of `CHANGELOG.md` (below the `# Changelog` header), before
   the previous `## [...]` entry.

   Format (same 7 categories as `/changelog`):
   ```markdown
   ## [1.3.0] — 2026-06-12

   ### 🔴 Breaking changes
   - <sha7> <subject>

   ### 🟡 Protocol surface changes
   - ...

   ### 🟠 Security
   - ...

   ### ✅ Features
   - ...

   ### 🔧 Fixes
   - ...

   ### 🧪 Test / CI
   - ...

   ### — Other
   - ...
   ```
   Omit empty sections.

### Phase 3 — Commit + tag + push

9. After `/sdk-test` completes (step 4), re-run `git status --short` to confirm
   the test run left no uncommitted artifacts. If it did, ensure they are covered
   by `.gitignore` — otherwise `git add` below will not pick them up, but the user
   should be aware.

10. Stage the two files:
    ```bash
    git add pyproject.toml CHANGELOG.md
    ```

11. Commit:
    ```bash
    git commit -m "chore: release v<semver>"
    ```

12. Tag:
    ```bash
    git tag -a "v<semver>" -m "Release v<semver>"
    ```

13. **Confirm before pushing:**
    "About to push commit + tag `v<semver>` from branch `<branch>` to origin. Proceed?"
    Wait for user confirmation. Never force-push.

14. On confirmation, push the current branch (not hardcoded `main`):
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
  - if this release shipped a /gh-review wave, close the resolved GH issues now:
      gh issue close <N> --repo wailuen/a2a-sdk \
        --comment "Fixed in v<semver> (<sha7>)."
```

## Rules

- **Never skip `/sdk-test`.** The test gate is the only thing standing between
  a broken SDK and pinned agents that can't upgrade.
- **Never force-push main or a tag.**
- **Never write a version into `pyproject.toml` to work around the step 3
  ancestry guard.** A version bump is a claim about ancestry, not just a
  number — reconcile the branch instead.
- **Never retitle `CHANGELOG.md`'s newest heading without updating
  `pyproject.toml` to match, or vice versa.** The step 2 agreement guard
  exists because this drifted silently once already (RT-002): a redteam
  finding's fix retitled the changelog heading but left pyproject.toml on the
  old number, so the two disagreed about which release was current until the
  next `/sdk-release` run caught it.
- If the user cancels at step 13, the commit and tag exist locally but are not
  pushed. They can push manually or run `/sdk-release` again with the same
  version (step 1 will fail gracefully — bump check catches the already-matching
  version and offers to push the existing tag).
- **Patch releases** (MAJOR.MINOR.PATCH with no change to FR count) are expected
  to have zero BREAKING commits in the changelog. If BREAKING commits exist for a
  patch bump, warn before proceeding.
- **Minor releases** may add features but not remove or narrow existing tool
  contracts. Flag any commits that look like contract narrowing.
