# agent-sdk harness — Claude Code conventions

The canonical agent conventions file is **`template/CLAUDE.md`** (one level up, at
`../template/CLAUDE.md` relative to this directory). That file is the single source
of truth for the SI table, credential model, SDK conventions, and workflow disciplines.

`harness/CLAUDE.md` (this file) intentionally contains no duplicated content.
The `/upgrade` skill's `harness-sync` step regenerates `template/CLAUDE.md` from
the SDK when invariants change — do not hand-edit the SI table or credential model
here; change them in `template/CLAUDE.md` and let `/upgrade` propagate.

## Harness-specific rules

- Harness skills live in `harness/skills/`; they are seeded into agent repos by
  `/new-agent` but are **not** modified by those repos.
- `harness/workspace/` is the workspace template; changes here propagate to new
  agents only — existing agent repos are unaffected.
- `harness/agents/` holds the agent definitions (redteam, analyst, planner, codify,
  debug, sdk-advisor, python-implementer). Edit them here; `/upgrade` re-seeds them.
- `harness/reference/sdk-security-invariants.md` is the grep-check reference for
  SI-1…SI-7. It must stay in sync with the SI table in `template/CLAUDE.md`.

## No-mock rule (SDK tests in `tests/`)

Never use `unittest.mock.patch`, `MagicMock`, or `AsyncMock` to substitute SDK
internals in `tests/`. Mocks diverge silently from the real implementation and
pass tests that fail at runtime. Permitted test doubles:

- **`agent_sdk.testing`** (`FakeModelClient`, `reply`, `tool_call`) — purpose-built
  stubs maintained alongside the real interface; these are the only approved model
  substitutes.
- **Real in-memory stores** — `InMemoryTaskStore`, `EncryptedSqliteStore` with a
  `tmp_path` fixture, `InMemoryCredentialStore`. Prefer these over any mock.
- **`respx`** — for asserting outbound HTTP calls from `SourceAdapter` code; never
  patch `httpx` directly.
- **`httpx.AsyncClient(app=..., base_url=...)`** — ASGI test client for route tests;
  exercises the full FastAPI stack without a network hop.

Violations are caught by `redteam` (treated as a HIGH finding — mocks on persistence
or protocol surfaces are equivalent to untested code).
