---
name: sdk-test
category: sdk-dev
description: "Run the full SDK test suite plus a live agent-stack-check against the alphageo example. Used by SDK contributors to confirm a change is clean before tagging a release."
---

# /sdk-test — SDK contributor test gate

Validates that a proposed SDK change passes all unit tests, integration tests,
and a live conformance check against the bundled example agent.

## Usage

```
/sdk-test [--no-example]
```

- `(no args)` — run all three legs: unit tests + integration tests + example stack-check
- `--no-example` — skip the alphageo example leg (faster, for fast iteration cycles)

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
   .venv/bin/mypy agent_sdk/ --ignore-missing-imports -q
   ```
   Report any errors. An error-free run prints "Success: no issues found."

### Leg 3 — Example stack-check (skipped with `--no-example`)

4. Confirm `examples/alphageo/` exists and has `.venv/` installed.
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

5. Boot the alphageo example in DEV_MODE from the SDK root (path matters):
   ```bash
   DEV_MODE=true examples/alphageo/.venv/bin/uvicorn src.main:app \
     --app-dir examples/alphageo --port 9001 --workers 1
   ```
   Run in background (stdout/stderr to a temp file). Poll
   `GET http://localhost:9001/health` for 200 (30 s timeout). On failure, cat the
   temp file and stop.

6. Invoke `/agent-verify --port 9001`. Surface the full report.

7. Tear down the example uvicorn process.

### Report

```
## SDK test — <git-sha7>
Unit tests:    <N passed> / <M failed> / <K skipped>  [<time>]
Type check:    PASS | FAIL (<N errors>)
Example boot:  OK | FAIL (skipped with --no-example)
Agent-verify:  PASS | FAIL | SKIPPED
OVERALL:       GREEN | RED

Failures:
  <test file>:<line>  <assertion>
```

## Rules

- **Zero failures required to tag a release.** If any leg is RED, stop and report —
  do not proceed to `/sdk-release`.
- **`--no-example` is for iteration only.** The full three-leg run is the release gate.
- Never silence a failing test with `# noqa` or `@pytest.mark.skip` without
  surfacing it as a known issue in `REVIEWS.md`.
