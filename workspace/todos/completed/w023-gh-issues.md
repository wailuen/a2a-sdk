# w023 — GitHub issues #78, #79, #81, #83, #84

Sourced from open issues on wailuen/a2a-sdk. All items are independent.
Run in parallel (group:G).
Target: 0.5.21.

---

- [ ] `GH-79` protocol/a2a: credential-forwarding extension uses URN not https:// URI — consumer allowlist incompatible ‖ group:G
  - Modifies: `agent_sdk/credentials/card.py`
  - Reads: `agent_sdk/credentials/card.py`
  - Severity: high
  - Root cause: `EXTENSION_URI` at `agent_sdk/credentials/card.py:27` is set to `'urn:agent-sdk:credential-forwarding:v1'`. A2A v0.3.0 defines `AgentExtension.uri` as a URL string; consumer allowlist implementations (including Claude.ai) filter for `https://` scheme and silently skip `urn:` entries, so the credential-forwarding extension is invisible to those consumers — credential forwarding silently deactivates without error.
  - AC:
    - `EXTENSION_URI` in `agent_sdk/credentials/card.py` is changed from `'urn:agent-sdk:credential-forwarding:v1'` to a stable `https://` URI (e.g. `'https://agent-sdk.dev/extensions/credential-forwarding/v1'`)
    - All string literal references to the old URN in tests and source files are updated to the new URI
    - Unit test asserts `credential_forwarding_extension().uri.startswith('https://')`
  - GH: https://github.com/wailuen/a2a-sdk/issues/79

- [ ] `GH-84` harness/workflow: wave archive gate allows false-green when deliverables are uncommitted ‖ group:G
  - Modifies: `.claude/workflows/sdk-wave.js`, `.claude/workflows/wave-cycle.js`
  - Reads: `.claude/workflows/sdk-wave.js`, `.claude/workflows/wave-cycle.js`
  - Severity: high
  - Root cause: `sdk-wave.js` phase 7 (archive) has no commit guard at all — lines 988–990 contain a comment explicitly deferring the GH-40 commit guard to `wave-cycle.js`, so a wave can archive with zero committed deliverables as long as pytest passes. `wave-cycle.js` does have the `ARCHIVE_INTENT_SCHEMA` guard (lines 1280–1313) using `wave.allScope` (Creates: ∪ Modifies:), but both files share a second gap: post-wave deliverables from codify/redteam phases (`workspace/learning/LRN-*.md`, `workspace/scenarios/results/`, new test files) are never declared in any todo's Creates:/Modifies: fields, so they fall outside `allScope` and the guard cannot catch them as uncommitted.
  - AC:
    - `sdk-wave.js` phase 7 includes a commit guard equivalent to `wave-cycle.js` lines 1280–1313 (using `ARCHIVE_INTENT_SCHEMA` and blocking archive when `offendingPaths` is non-empty)
    - `ARCHIVE_INTENT_SCHEMA` is added to `sdk-wave.js` (copy from `wave-cycle.js` lines 225–234, adapted)
    - Both `sdk-wave.js` and `wave-cycle.js` augment the archiveIntent agent prompt with a second cross-reference pass: flag any dirty/untracked paths under `tests/`, `workspace/learning/`, `workspace/scenarios/results/`, and `workspace/prd/` even if they are not in `wave.allScope` — add an `offendingHarnessPaths` array field to `ARCHIVE_INTENT_SCHEMA`
    - Archive is blocked in both files if `offendingHarnessPaths` is non-empty
    - A test or fixture documents the expected blocking behavior (comment or test in `tests/test_workflows.py` if the file exists)
  - GH: https://github.com/wailuen/a2a-sdk/issues/84

- [ ] `GH-78` protocol/a2a: TaskStatus.error field is not in A2A v0.3.0 spec — undeclared extension ‖ group:G
  - Modifies: `agent_sdk/routes/agent_card.py`
  - Reads: `agent_sdk/models/a2a.py`, `agent_sdk/routes/agent_card.py`
  - Severity: medium
  - Root cause: `TaskStatus.error` (`WireError | None`) at `agent_sdk/models/a2a.py:113` is an intentional SDK extension (flagged with a code comment). The field is harmless at the wire level — `exclude_none=True` suppresses it when `None`. The gap is that no `AgentExtension` entry is declared in `capabilities.extensions[]`, so a strict consumer cannot distinguish intentional extension from accidental schema drift. The `WireError` field itself must NOT be removed (the comment explicitly records the intent to deviate from spec). The fix is additive: declare the extension in `build_agent_card()`.
  - AC:
    - `build_agent_card()` in `agent_sdk/routes/agent_card.py` adds an `AgentExtension` entry for the TaskStatus.error field with a stable URI (e.g. `'https://agent-sdk.dev/extensions/task-error/v1'`) and `required=False`
    - The URI uses `https://` scheme (consistent with the GH-79 fix for credential-forwarding)
    - Unit test asserts `build_agent_card()` output contains a `capabilities.extensions` entry whose `uri` matches the task-error extension URI
    - `TaskStatus.error` field in `a2a.py` is NOT removed
  - GH: https://github.com/wailuen/a2a-sdk/issues/78

- [ ] `GH-81` sdk/loop: add agent_sdk.contrib.scheduler — domain schedulers silently non-functional ‖ group:G
  - Creates: `agent_sdk/contrib/scheduler.py`, `agent_sdk/scheduler.py`, `tests/test_scheduler.py`
  - Modifies: `agent_sdk/contrib/__init__.py`, `agent_sdk/app.py`
  - Reads: `agent_sdk/app.py`, `agent_sdk/contrib/__init__.py`, `agent_sdk/__init__.py`
  - Note: `agent_sdk/__init__.py` was declared in Modifies: but was not modified — the stub-module strategy (`agent_sdk/scheduler.py` raising ImportError) satisfied the migration-guide AC without needing an __init__.py re-export.
  - Severity: high
  - Root cause: `agent_sdk.scheduler` does not exist. Domain agents that write `from agent_sdk import scheduler` crash with `ModuleNotFoundError`. If wrapped in `try/except ImportError`, the agent boots normally but the scheduled job is permanently dead with no observable signal. The SDK has a canonical scheduling hook — `lifespan_extras` passed to `Agent()` — but it is only documented in a buried docstring at `app.py:137–139` and requires manual async plumbing that most domain authors won't write. The fix is a `contrib.scheduler` module that wraps `lifespan_extras` into a decorator-based API matching what domain authors already reach for.
  - AC:
    - `agent_sdk/contrib/scheduler.py` defines a `Scheduler` class with:
      - `scheduler.cron(interval_seconds: int)` — decorator that registers an async or sync callable as a recurring background job
      - `scheduler.lifespan` — an async context manager compatible with `lifespan_extras` that starts all registered jobs on enter, cancels them on exit
    - `from agent_sdk.contrib import Scheduler` works after install
    - `from agent_sdk import scheduler` raises a clear `ImportError` with a message pointing to `from agent_sdk.contrib import Scheduler` (do NOT silently create a module-level singleton at `agent_sdk.scheduler` — that ambiguates the API surface; the error message is the migration guide)
    - Alternatively: expose `agent_sdk.scheduler` as a direct import alias for `agent_sdk.contrib.scheduler` if the team prefers the short import — but decide one way and document it; do not leave it as a silent crash
    - `agent_sdk/contrib/__init__.py` exports `Scheduler`
    - `tests/test_scheduler.py` covers: (1) `@sched.cron(5)` registers a job; (2) entering `sched.lifespan` starts background tasks; (3) exiting `sched.lifespan` cancels them cleanly; (4) the module is importable from `agent_sdk.contrib`
    - The `Agent.__init__` docstring at `app.py:137–139` is updated to reference `from agent_sdk.contrib import Scheduler` and show a minimal one-liner example
  - GH: https://github.com/wailuen/a2a-sdk/issues/81

- [ ] `GH-83` harness/skills: acceptance skill uses Workflow({name}) which drops args — switch to scriptPath ‖ group:G
  - Modifies: `harness/skills/acceptance/SKILL.md`
  - Reads: `harness/skills/acceptance/SKILL.md`, `harness/workflows/acceptance-api.js`
  - Severity: high
  - Root cause: `harness/skills/acceptance/SKILL.md` at lines 235–245 invokes the acceptance workflow via `Workflow({name: 'acceptance-api', args: {...}})`. A bug in Claude Code's built-in Workflow engine causes `args` to be `undefined` inside named-workflow scripts — only the `scriptPath` invocation form correctly forwards `args`. `harness/workflows/acceptance-api.js` reads `args.scenarios`, `args.baseUrl`, etc. at startup; with `args` undefined it throws `TypeError` immediately and the entire acceptance run fails.
  - AC:
    - In `harness/skills/acceptance/SKILL.md`, the `Workflow({name: 'acceptance-api', ...})` call at lines 235–245 is replaced with `Workflow({scriptPath: '<repo-root>/harness/workflows/acceptance-api.js', args: {...}})` where `<repo-root>` is resolved at invocation time (e.g. the skill instructs Claude to use the absolute path of `harness/workflows/acceptance-api.js` relative to the project root it detects via `git rev-parse --show-toplevel` or `process.cwd()`)
    - The `args` object shape is unchanged — only the dispatch form changes from `name:` to `scriptPath:`
    - A comment in SKILL.md explains why `scriptPath` is used instead of `name` (Claude Code built-in bug; remove the comment once the upstream fix ships)
    - `harness/workflows/acceptance-api.js` is NOT modified — the fix is in the caller only
  - GH: https://github.com/wailuen/a2a-sdk/issues/83
