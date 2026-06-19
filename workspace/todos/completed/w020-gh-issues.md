# w020 — GitHub issues #70

Sourced from open issues on wailuen/a2a-sdk. All items are independent.
Run in parallel (group:G).
Target: 0.5.17.

> Planning rule: every in-repo todo's `Modifies:`/`Reads:` path MUST be git-tracked
> in a2a-sdk. GH-70d is re-scoped OUT OF REPO (`template/` is gitignored/untracked) —
> it lands as a PR against `wailuen/agent-template`, not from this wave. Marked `[~]`.

---

- [x] `GH-70a` harness/skills/upgrade: replace uv pip install with uv sync --frozen + add uv lock step ‖ group:G
  - Modifies: `harness/skills/upgrade/SKILL.md`
  - Reads: `harness/skills/upgrade/SKILL.md`
  - Severity: medium
  - Root cause: Step 7 of the upgrade skill calls `uv pip install -e` (editable install of the bumped wheel), which ignores the lockfile entirely. After bumping the SDK SHA in pyproject.toml, `uv lock` must run first to regenerate uv.lock, then `uv sync --frozen` installs from the new lockfile. Without this, the lockfile diverges from the installed state after every upgrade, breaking reproducibility.
  - AC:
    - Step 6 (pyproject.toml SHA bump) is immediately followed by a `uv lock` command that regenerates uv.lock
    - Step 7 uses `uv sync --frozen` (not `uv pip install -e`) for the actual install
    - Rollback notes in the skill explicitly include restoring uv.lock alongside pyproject.toml
    - The upgrade commit instruction includes `git add uv.lock` alongside `pyproject.toml`
  - GH: https://github.com/wailuen/a2a-sdk/issues/70

- [x] `GH-70b` harness/skills/setup: replace uv pip install (+ pip fallback) with uv sync --frozen + generate initial uv.lock ‖ group:G
  - Modifies: `harness/skills/setup/SKILL.md`
  - Reads: `harness/skills/setup/SKILL.md`
  - Severity: medium
  - Root cause: Phase 5 step 1 of the setup skill uses `uv pip install -e` with a pip fallback, bypassing the lockfile. New agents scaffolded by /setup never get a uv.lock, so their first `uv sync --frozen` (which the standardised Dockerfile will require) fails with "no lockfile found". The fix adds a `uv lock` call in Phase 2 (after placeholder substitution, while pyproject.toml is fresh) so uv.lock is committed with the initial scaffold.
  - AC:
    - Phase 2 (or a dedicated Phase 2.5 step) includes `uv lock` after template placeholder substitution completes
    - Phase 5 step 1 uses `uv sync --frozen` instead of `uv pip install -e`
    - The pip fallback is removed — uv is required (consistent with the rest of the harness)
    - The skill's "initial commit" instruction includes `git add uv.lock`
  - GH: https://github.com/wailuen/a2a-sdk/issues/70

- [x] `GH-70c` harness/skills/new-agent: replace pip install with uv sync --frozen + generate initial uv.lock ‖ group:G
  - Modifies: `harness/skills/new-agent/SKILL.md`
  - Reads: `harness/skills/new-agent/SKILL.md`
  - Severity: medium
  - Root cause: Phase 5 step 1 of new-agent uses `.venv/bin/pip install -e`, which bypasses uv and the lockfile entirely. Like setup, newly scaffolded agents have no uv.lock, making them incompatible with `uv sync --frozen` from the first install. The fix adds `uv lock` after the template render (Phase 2 or Phase 4) so the lockfile is generated before the first install and committed with the scaffold.
  - AC:
    - A `uv lock` step is added after template render (Phase 2 or 4) before the first install runs
    - Phase 5 step 1 uses `uv sync --frozen` instead of `.venv/bin/pip install -e`
    - No bare pip calls remain in the new-agent skill
    - The skill's scaffold-commit instruction includes `git add uv.lock`
  - GH: https://github.com/wailuen/a2a-sdk/issues/70

- [~] `GH-70d` template/Dockerfile: install uv + replace pip install with uv sync --frozen ‖ group:G
  - **OUT OF REPO — cannot land here.** `template/` is gitignored (`.gitignore:38`)
    and fully untracked (`git ls-files template/` → 0; commit e7bf0a1 stopped tracking
    it). The canonical Dockerfile lives in the separate `wailuen/agent-template` repo.
    This todo's `Modifies:`/`Reads:` path is not git-tracked in a2a-sdk, so the change
    cannot be committed or propagated from here. Re-file and land it as its own PR
    against `wailuen/agent-template`; do not mark GH-70d done from this wave.
  - Repo: `wailuen/agent-template` (NOT a2a-sdk)
  - Modifies: `Dockerfile` (in agent-template repo root)
  - Reads: `Dockerfile` (in agent-template repo root)
  - Severity: medium
  - Root cause: The build stage uses bare `pip install --no-cache-dir --prefix=/install .` which bypasses uv and the lockfile. Any agent built from the template gets a non-reproducible Docker image — package versions are resolved fresh on every `docker build`. With uv present, `uv sync --frozen` pins to the lockfile committed at scaffold time, making image builds reproducible. The SSH `--mount=type=ssh` must be preserved since template agents typically pull private deps via git+ssh.
  - AC (apply in the agent-template repo):
    - `uv` is installed in the build stage (e.g. COPY from `ghcr.io/astral-sh/uv:latest`)
    - `COPY uv.lock ./` is added alongside `COPY pyproject.toml ./` so the lockfile is available at build time
    - The `pip install --no-cache-dir --prefix=/install .` call is replaced with bare `uv sync --frozen` (no `--no-dev` flag: `--no-dev` controls `[dependency-groups]`, not `[project.optional-dependencies]` extras; extras are already excluded by default, so `--no-dev` is a silent no-op on extras-only layouts like this template)
    - The SSH `--mount=type=ssh` is preserved on the uv sync RUN layer
    - uv installs into the project venv at `/app/.venv`, not a `/install` prefix. The final stage must `COPY --from=build /app/.venv /app/.venv` (not `COPY --from=build /install /usr/local`) and run via `/app/.venv/bin/...`.
    - No bare `pip` calls remain in the Dockerfile
  - GH: https://github.com/wailuen/a2a-sdk/issues/70 (close GH-70d against agent-template, not a2a-sdk)
