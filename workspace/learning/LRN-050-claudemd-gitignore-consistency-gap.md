# LRN-050 — CLAUDE.md/gitignore consistency gap

| Field      | Value                          |
|------------|--------------------------------|
| Category   | security                       |
| Severity   | critical                       |
| Source     | gh-review                      |
| Date       | 2026-06-18                     |
| Wave       | w019                           |
| GH issue   | GH-66                          |

## Finding

`harness/.gitignore` was entirely absent — no credential-file globs existed anywhere in the repository (neither in ADR-000 nor ADR-001 areas). `CLAUDE.md` documented those files as gitignored, but the actual `.gitignore` entries were never written. Any developer running `/provision` and then `git add workspace/` would silently commit credential inventory files (Azure keys, API keys, etc.) to version control with no warning.

## Pattern

**CLAUDE.md/gitignore consistency gap** — documentation claims files are gitignored; `.gitignore` patterns are absent.

## Root cause

Harness CLAUDE.md was updated (or the credential store feature was added) without a corresponding change to `.gitignore`. There was no automated or manual cross-check step to verify that every file class described as "gitignored" in documentation actually had a matching `.gitignore` entry.

## Prevention

1. After every harness update that introduces or removes credential-adjacent file classes, diff `harness/.gitignore` against every "gitignored" claim in `CLAUDE.md` and `workspace/adr/`.
2. Add a CI/pre-commit check: parse CLAUDE.md for `gitignored` annotations and assert matching `.gitignore` glob patterns exist.
3. Treat a missing `.gitignore` entry for any credential file as a **blocking** review defect, not advisory.

## Checklist for future harness updates

- [ ] Run `grep -n 'gitignore\|git-ignore' harness/CLAUDE.md` and list every file class mentioned.
- [ ] Confirm each class has a glob in `harness/.gitignore` (or root `.gitignore`).
- [ ] Confirm `workspace/adr/` credential-file patterns are covered.
- [ ] If any gap found, add the glob and commit before merging.
