# LRN-051 — uv --no-dev is a silent no-op on extras-only dependency layouts

| Field      | Value                          |
|------------|--------------------------------|
| Category   | ops                            |
| Severity   | medium                         |
| Source     | redteam (RT-005)               |
| Date       | 2026-06-18                     |
| Wave       | w020                           |
| GH issue   | GH-70d                         |

## Finding

An AC for GH-70d instructed `uv sync --frozen --no-dev` in the Dockerfile build stage. The `--no-dev` flag is a no-op when the project's non-production dependencies are declared under `[project.optional-dependencies].dev` (PEP 621 extras) rather than under `[dependency-groups]` (uv/PEP 735 groups).

`--no-dev` controls only `[dependency-groups]` entries. `[project.optional-dependencies]` extras are excluded by default unless `--extra <name>` or `--all-extras` is passed. The flag silently does nothing on extras-only layouts, giving a false sense of prod-isolation while adding noise to the command.

## Pattern

**`--no-dev` applied to extras-only layout** — `uv sync --frozen --no-dev` used where deps are declared under `[project.optional-dependencies].dev`, not `[dependency-groups].dev`.

## Root cause

Confusion between two distinct uv/PEP mechanisms:

| Mechanism | Declared in | Excluded by | Include with |
|-----------|-------------|-------------|--------------|
| Extras | `[project.optional-dependencies]` | default (always excluded) | `--extra <name>` |
| Dependency groups | `[dependency-groups]` | `--no-dev` / `--no-group <name>` | default (always included) |

Projects scaffolded from the agent-template use extras (`[project.optional-dependencies].dev`) for test dependencies. A prod Docker image is correct with bare `uv sync --frozen` — no flag needed.

## Prevention

1. Before writing `uv sync --frozen --no-dev` in any Dockerfile or CI step, confirm the project uses `[dependency-groups]` (not extras) for dev deps.
2. If the project uses `[project.optional-dependencies].dev`, use bare `uv sync --frozen` — extras are already excluded.
3. AC reviewers: flag any `--no-dev` usage in extras-only projects as a no-op that should be removed.

## Correct Dockerfile pattern (extras-only layout)

```dockerfile
# Build stage
RUN --mount=type=ssh uv sync --frozen
# (no --no-dev; extras are already excluded by default)

# Final stage
COPY --from=build /app/.venv /app/.venv
```
