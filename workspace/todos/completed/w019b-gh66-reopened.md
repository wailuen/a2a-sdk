# w019b — GH-66 reopened (carved out of w019)

Carved out of `w019-gh-issues.md` (RT-005, 2026-06-18): GH-66 was marked complete
and archived, but AC #2 (verify inside a scaffolded agent repo) was satisfied only
by inspecting SDK-internal files. A `--from-github` gitignore gap remains, so a
critical-severity credential leak path is still open. The other five w019 items
(GH-58/60/62/63/65) are genuinely complete and stay in `completed/w019-gh-issues.md`.

Target: next patch release.

---

- [x] `GH-66` CLAUDE.md states ADR-001-* credential files are gitignored but the `--from-github` scaffold path is unverified — silent security gap ‖ group:G
  - Modifies: `harness/skills/new-agent/SKILL.md`, `template/.claude/skills/new-agent/SKILL.md`
  - Reads: `/Users/wailuen/Development/a2a-sdk/.gitignore`, `template/.gitignore`, `harness/.gitignore`
  - Severity: critical
  - Root cause: `harness/.gitignore` and `template/.gitignore` both carry the `workspace/adr/ADR-000-*-credentials.md` and `workspace/adr/ADR-001-*-credentials.md` globs, but the `--from-github` scaffold path (GitHub template repo `wailuen/agent-template`) had no explicit remediation if the template lacked the globs.
  - AC:
    - [x] `harness/.gitignore` contains both `workspace/adr/ADR-000-*-credentials.md` and `workspace/adr/ADR-001-*-credentials.md` — confirmed present, not regressed
    - [~] Re-scaffold an agent with `--from-github` — live clone of `wailuen/agent-template` is an external network operation not automatable here; mitigated by AC #3
    - [x] `--from-github` gap closed: Phase 2 step 4 of `harness/skills/new-agent/SKILL.md` and `template/.claude/skills/new-agent/SKILL.md` now mandate a `git check-ignore -v workspace/adr/ADR-001-dev-credentials.md` probe immediately after clone, and provide an explicit fallback that appends both globs and stages the change if the probe fails; skill blocks on Phase 3 until the check passes
    - [x] No committed credential files in `workspace/adr/` — `git ls-files workspace/adr/` returns no ADR-000-*-credentials.md or ADR-001-*-credentials.md matches
  - GH: https://github.com/wailuen/a2a-sdk/issues/66
  - History: originally completed in w019 then reopened (RT-002, 2026-06-18); carved into its own active wave (RT-005, 2026-06-18); fixed 2026-06-18 by hardening the scaffold skill to detect and patch the gap at scaffold time rather than relying on the GitHub template to carry the globs.
