---
name: sdk-test
category: sdk-dev
description: "Run the full SDK test gate: unit tests, mypy, static protocol conformance audit, and an optional live boot check against the alphageo example. Used by SDK contributors before tagging a release."
---

# /sdk-test — SDK contributor test gate

Validates that a proposed SDK change passes all unit tests, type checking,
and protocol conformance — **before** the SDK is tagged. Conformance is
verified here, at the SDK, not repeated per downstream agent on every upgrade.

## Usage

```
/sdk-test [--no-example]
```

- `(no args)` — run all four legs: unit tests + mypy + static conformance + example boot
- `--no-example` — skip Leg 4 (example boot); Legs 1–3 still run

## Steps

### Leg 1 — Unit + integration tests

1. Confirm the virtual environment is up to date:
   ```bash
   VIRTUAL_ENV=.venv uv pip install -e ".[dev]" -q
   ```

2. Run the full test suite:
   ```bash
   .venv/bin/pytest -q tests/ --tb=short
   ```
   Report: number passed, failed, skipped, and total time.
   On failure: surface the failing test file and line number, the assertion, and
   the actual vs expected value. Do NOT suppress — fix or flag.

### Leg 2 — Type check

3. Run `mypy` on the SDK source:
   ```bash
   .venv/bin/mypy agent_sdk/ --ignore-missing-imports
   ```
   **Zero-tolerance gate.** Any error is a release blocker — do not proceed.
   A clean run prints "Success: no issues found in N source files."

### Leg 3 — Static protocol conformance

Audit the SDK's own protocol surfaces for A2A, AG-UI, A2UI, and MCP
conformance **before** tagging. This is the single canonical gate —
downstream agents on this SDK version inherit the result and do not
re-run the stack-check on every upgrade.

Run the agent-interop umbrella in static mode against the SDK source:

```
/agent-stack-check . --static-only
```

Report the verdict verbatim. Any finding rated HIGH or CRITICAL is a
release blocker. MEDIUM/LOW findings must be acknowledged before tagging
(either fixed or recorded as deferred with a rationale).

> **Why here and not downstream:** The routes in `agent_sdk/routes/`
> (A2A, AG-UI, A2UI, MCP) are identical across every agent on the same
> SDK version. Checking them once at release time — and not again per
> agent upgrade — eliminates redundant work and prevents false negatives
> when an agent can't boot due to missing API keys.

### Leg 4 — Example boot check (skipped with `--no-example`)

5. Confirm `examples/alphageo/` exists and has `.venv/` installed.
   If not installed, run from the SDK root:
   ```bash
   python3.12 -m venv examples/alphageo/.venv
   VIRTUAL_ENV=examples/alphageo/.venv uv pip install -e "examples/alphageo/[dev]"
   ```
   After installing, cross-check that the SDK under test is the one installed:
   ```bash
   examples/alphageo/.venv/bin/python -c "import agent_sdk; print(agent_sdk.__file__)"
   ```
   Confirm the path points into `agent_sdk/` in the current repo (not a pip cache).
   If it points elsewhere, the example is not testing the current SDK — emit a
   warning and offer to reinstall with `--no-cache-dir`.

6. Boot the alphageo example in DEV_MODE from the SDK root (path matters):
   ```bash
   DEV_MODE=true examples/alphageo/.venv/bin/uvicorn src.main:app \
     --app-dir examples/alphageo --port 9001 --workers 1
   ```
   Run in background (stdout/stderr to a temp file). Poll
   `GET http://localhost:9001/health` for 200 (30 s timeout). On failure, cat the
   temp file and stop.

7. Invoke `/agent-verify --no-stack-check --port 9001`. Surface the full report.
   The `--no-stack-check` flag is intentional: Leg 3 already ran the static
   conformance audit; the example boot only needs to confirm the agent starts
   and the OAuth chain is wired.

8. Tear down the example uvicorn process.

### Report

```
## SDK test — <git-sha7>
Unit tests:    <N passed> / <M failed> / <K skipped>  [<time>]
Type check:    PASS | FAIL (<N errors>)
Conformance:   PASS | FAIL (<N critical> <M high> findings)  [static]
Example boot:  OK | FAIL (skipped with --no-example)
Agent-verify:  PASS | FAIL | SKIPPED
OVERALL:       GREEN | RED

Failures:
  <test file>:<line>  <assertion>
Conformance blockers:
  <finding file:line>  <description>
```

## Rules

- **Zero failures required to tag a release.** If any leg is RED, stop and report —
  do not proceed to `/sdk-release`.
- **Zero mypy errors.** The type check is a hard gate, not advisory. Any new error
  introduced by a change is a blocker; fix it before tagging. Baseline is 0 errors.
- **Zero pytest warnings.** `filterwarnings = ["error"]` is set in `pyproject.toml`.
  A warning that becomes an error in tests means the code or the test needs fixing —
  never add a `# noqa` or warning suppression to paper over it.
- **Conformance is an SDK-level gate, not a downstream one.** Leg 3 runs once here
  before tagging. Downstream agents on this SDK version inherit the conformance result
  — they do NOT re-run `/agent-stack-check` on every upgrade. Their `/upgrade` skill
  runs `/agent-verify --no-stack-check` (boot health + OAuth-chain only).
- **`--no-example` is for iteration only.** The full four-leg run is the release gate.
- Never silence a failing test with `# noqa` or `@pytest.mark.skip` without
  surfacing it as a known issue in `REVIEWS.md`.
