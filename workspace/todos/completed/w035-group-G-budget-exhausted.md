wave: w035
group: G
date: 2026-07-19
round_count: 5
status: budget-exhausted

## Findings

### RT-001
- severity: low
- file: .claude/workflows/sdk-wave.js
- status: FIXED (2026-07-19)
- description: The archiveIntent import-resolution rules (~lines 1070-1115) never handle the case where the imported <name> is a sub-PACKAGE (a directory with __init__.py) rather than a submodule file or a re-exported symbol. The prompt's own absolute worked example is factually wrong about the repo layout — line 1077 says `from agent_sdk import routes` -> 'check for agent_sdk/routes.py', but agent_sdk/routes.py does not exist (agent_sdk/routes/ is a package). With no `<name>/__init__.py` branch, both the absolute and relative bare from-import rules fall through to `<pkg-path>/__init__.py`, so `from agent_sdk import newpkg` (or relative `from . import newpkg`) for a mid-wave-extracted untracked sub-package resolves to an always-tracked parent __init__.py and is never flagged — a false-negative in exactly the gate GH-118 was built to close.
- fix: `.claude/workflows/sdk-wave.js` now carries an explicit "RT-001 (round-5)" sub-package branch in both the absolute from-import rule (~lines 1080-1086) and the relative bare from-import rule (~lines 1122-1128): before falling back to `<pkg-path>/__init__.py` (symbol re-export), the prompt checks whether `<pkg-path>/<name>/__init__.py` exists on disk and, if so, resolves to that file as the sub-package. The worked example is corrected to `from agent_sdk import routes` -> `agent_sdk/routes.py` does NOT exist, but `agent_sdk/routes/__init__.py` DOES -> resolves to `agent_sdk/routes/__init__.py`. Verified at `.claude/workflows/sdk-wave.js:1080-1086,1122-1128`.
- sdkCandidate: false

### RT-002
- severity: low
- file: tests/test_workflows.py
- status: FIXED (2026-07-19)
- description: The GH-118 AC requires that the gate 'does not false-positive on tracked-but-modified modules or third-party/stdlib imports', and the prompt contains the guardrails that enforce it ('Ignore stdlib and third-party imports' and the 'A resolved path that IS tracked ... is never an offender' clause). But unlike the RT-001 guardrails ('EXISTS on disk'/'mis-resolution', pinned by test_rt001_undeclared_import_offender_must_exist_on_disk), no static test pins these two false-positive guards to the live archiveIntent prompt — a future edit could silently delete them, reintroducing archive-gate false-positives on stdlib/tracked imports, with the whole suite still green.
- fix: `tests/test_workflows.py` now has `test_rt002_archive_intent_prompt_ignores_stdlib_and_third_party_imports` (asserts `"Ignore stdlib and third-party imports"` is present in the live archiveIntent prompt) and `test_rt002_archive_intent_prompt_tracked_resolved_path_never_an_offender` (asserts the "A resolved path that IS tracked ... is never an offender" wording is present), mirroring the RT-001-pinning `test_rt001_undeclared_import_offender_must_exist_on_disk` pattern. Verified with `.venv/bin/pytest -q tests/test_workflows.py -k "rt001 or rt002"` -> 22 passed, and the full suite `.venv/bin/pytest -q tests/` -> 1163 passed.
- sdkCandidate: false

## Instruction

All findings resolved and test-covered; no re-run of /wave w035 needed. Relocated from
workspace/todos/deferred/ to workspace/todos/completed/ per LRN-100 (a budget-exhausted
deferred marker must be removed or relocated the moment its findings land, or it falsely
reports the wave as incomplete).
