# w071 — GitHub issues 276–279

Sourced from open issues on wailuen/a2a-sdk (deferred-labelled #186 skipped). Four items in two groups: G1 (SDK, two independent items) and G2 (wave runner, two items in order).
Target: 0.27.0 (minor: visible behaviour changes to `current_identity()` in admin try and to OAuth labels; new runner resume behaviour).

Rulings (recorded before this wave; where an AC differs, the ruling wins):
- GH-276: https://github.com/wailuen/a2a-sdk/issues/276#issuecomment-6719517060
- GH-277: https://github.com/wailuen/a2a-sdk/issues/277#issuecomment-6719517260
- GH-278: https://github.com/wailuen/a2a-sdk/issues/278#issuecomment-6719517451
- GH-279: https://github.com/wailuen/a2a-sdk/issues/279#issuecomment-6719517630

Each item adds its own entry to `CHANGELOG.md` under a single `## [Unreleased]` heading (create it once if absent, LRN-494), naming every changed `agent_sdk/` or `harness/` file by full repo path (LRN-491). Tests run against `build_app()` over the ASGI transport where a route is involved (LRN-496). A test that guards a behaviour must fail when that behaviour is removed (LRN-560).

---

## G1 — SDK identity and labels

- [ ] `GH-276` sdk/console: admin try-tool runs the tool with no caller identity bound ‖ group:G1
  - Modifies: `agent_sdk/routes/admin.py` (try-tool route, ~572-600), `tests/test_gh185_current_identity.py`, `docs/tools.md` (~161, `current_identity()`), `CHANGELOG.md`
  - Reads: `agent_sdk/auth/context.py` (`bind_identity` / `unbind_identity`), `agent_sdk/credentials/forwarding.py` (`bind`, `unbind`, `parse_header`, `HEADER_NAME`), `agent_sdk/routes/mcp.py` (how `tools/call` binds both), `agent_sdk/auth/middleware.py` (`require_admin`)
  - Depends: (none)
  - Severity: medium
  - Root cause: the route declares `dependencies=[Depends(require_admin)]`, so the resolved `Identity` is discarded, and nothing binds it (or forwarded credentials) around `entry.invoke_any(...)`; `current_identity()` is `None` inside the tool.
  - AC: the route takes `identity: Identity = Depends(require_admin)`; right before `invoke_any` it binds the identity with `bind_identity` and the forwarded credentials with `forwarding.bind(forwarding.parse_header(request.headers.get(forwarding.HEADER_NAME)))`; both are unbound in a `finally` that covers every exit (success, AgentError, validation error, timeout, catch-all). Response bytes for every outcome are unchanged.
  - AC (docs): `docs/tools.md` states that admin try-tool binds the admin key's identity and forwarded credentials, like MCP. CHANGELOG lists it as a visible behaviour change (`current_identity()` is no longer `None` in admin try).
  - Tests: (1) a tool recording `current_identity()` called via `POST /admin/api/tools/{name}/try` with an admin key sees that admin Identity (kind `api_key`, admin true, its label); (2) after the request, and across two requests in a row, nothing stays bound, including when the tool raises AgentError and when it times out; (3) a non-admin key gets 403 and never binds; (4) a tool reading forwarded credentials sees the `X-Agent-Credentials` value and they are unbound after.
  - GH: https://github.com/wailuen/a2a-sdk/issues/276
  - SI: SI-2  # No identity or credential value in any log line or error text added by this change.

- [ ] `GH-277` protocol/oauth: token label falls back to the client's self-chosen client_name ‖ group:G1
  - Modifies: `agent_sdk/routes/oauth.py` (token endpoint, ~1138-1143), `agent_sdk/auth/oauth_tokens.py` (`rotate_refresh`, ~476), `DESIGN.md` (~436), `docs/` page that documents `current_identity()` / OAuth labels (find it), a new `tests/test_gh277_oauth_label.py`, `tests/test_gh152_idp_off_regression.py` (extend only), `CHANGELOG.md`
  - Reads: `agent_sdk/auth/oidc.py` (~360-366, the IdP label), `agent_sdk/auth/oauth_tokens.py` (`verify`, ~584, the `oauth:<client_id[:8]>` fallback), `agent_sdk/routes/oauth.py` (admin-key consent `mint_code` ~975, one-time consent ~721, DCR `client_name` check ~386-393)
  - Depends: (none)
  - Severity: medium
  - Root cause: `label = meta.get("label") or client.get("client_name")` makes the DCR client's self-chosen name the user's display label whenever there is no IdP username/email claim (always, on the admin-key and one-time consent paths), and refresh rotation copies it for the whole family.
  - AC: the token label comes only from `meta["label"]`; with none, it is `None` and `verify()` shows the existing `oauth:<client_id[:8]>` tag. `client_name` is never read for a label anywhere in `agent_sdk/`.
  - AC (existing families): in `rotate_refresh`, a stored label that equals the client's registered `client_name` is cleared to `None` before the new pair is stored. Other labels are kept unchanged.
  - AC (docs): DESIGN.md (~436) and the `current_identity()` docs say the label comes only from the IdP claim, else `oauth:<client_id[:8]>`, `client_name` is never used, and `Identity.user` is the identity of record. CHANGELOG entry.
  - Tests: (1) admin-key consent and (2) one-time consent with `client_name="alice@corp"` give `Identity.label == "oauth:<cid[:8]>"` and the label never contains `alice@corp`; (3) IdP flow with no `preferred_username`/`email` gives the `oauth:` tag and `Identity.user` is set; (4) IdP flow with `preferred_username` keeps the sanitized IdP label; (5) a refresh family whose stored label equals `client_name` rotates to the `oauth:` tag; a family with an IdP label keeps it; (6) token response bytes unchanged with IdP off (extend `test_gh152_idp_off_regression.py`).
  - GH: https://github.com/wailuen/a2a-sdk/issues/277
  - SI: SI-5  # A label shown as "who" must never be chosen by the client; only the IdP or the server sets it.

## G2 — wave runner resume and frozen wave file

All changes in this group go into all three runner copies: `harness/workflows/wave-cycle.js`, `.claude/workflows/wave-cycle.js` (byte-identical copy of the first) and `.claude/workflows/sdk-wave.js` (same logic, lines about 7 higher). Tests live in `tests/test_wave_cycle_behaviour.py`, which already loops over both runners (`RUNNERS`, ~935); add a check that the two `wave-cycle.js` copies stay byte-identical if none exists.

- [ ] `GH-278` harness/workflow: wave-cycle.js has no resume-at-archive ‖ group:G2
  - Modifies: `harness/workflows/wave-cycle.js` (TODO_SCAN_PY ~464, `parseWave` ~534, empty-scope ~889, phase dispatch), `.claude/workflows/wave-cycle.js`, `.claude/workflows/sdk-wave.js`, `harness/skills/wave/SKILL.md` (~117, resume), `tests/test_wave_cycle_behaviour.py`, `CHANGELOG.md`
  - Reads: `harness/wave_scope.py` (~38, ~205: `[~]` meaning), `harness/skills/implement/SKILL.md` (~82: who ticks `[x]`)
  - Depends: (none)
  - Severity: medium
  - Root cause: only `[~]` todos are skipped, so a re-run after a blocked archive re-implements every `[x]` todo (repeating side effects such as pushes and live runs); marking them `[~]` instead empties the scope and aborts with `empty-scope`.
  - AC: TODO_SCAN_PY reports `done: true` for `[x]` todos next to `skip`; `[x]` todos are never dispatched to implementers and are logged by id as skipped; their `Creates:`/`Modifies:` paths stay in the wave scope (scope rescans and the archive gate unchanged).
  - AC (auto resume): when every todo is `[x]` or `[~]` and at least one is `[x]`, the run skips plan review, implement, unit/phase redteam and protocol audit, and runs only the pre-archive gate, the archive-commit gate and archive; it never returns `empty-scope`.
  - AC (forced): optional `args.resumeAt: "archive"` takes that path even with open todos; any other value fails fast with a clear error before any agent runs.
  - AC (docs): `harness/skills/wave/SKILL.md` explains `[x]` vs `[~]` and the resume behaviour.
  - Tests: (1) one `[x]` and one `[ ]` todo: only the `[ ]` one reaches an implementer; (2) all-`[x]`: no implementer, plan review or redteam agent runs, gate:pre-archive and archive do, no `empty-scope`; (3) `resumeAt: "archive"` jumps to archive; (4) `resumeAt: "bogus"` fails fast; (5) `[x]` paths still in scope. Each for every runner in `RUNNERS`.
  - GH: https://github.com/wailuen/a2a-sdk/issues/278

- [ ] `GH-279` harness/workflow: wave-cycle.js ignores todos and Depends added mid-run ‖ group:G2
  - Modifies: `harness/workflows/wave-cycle.js` (`parseWave`, `deriveGroupDeps` ~641-656, tier loop ~1316-1363, pre-archive), `.claude/workflows/wave-cycle.js`, `.claude/workflows/sdk-wave.js`, `harness/skills/wave/SKILL.md`, `harness/skills/todos/SKILL.md` or the planner instructions that define the wave file format (find where `Depends:` is specified), `tests/test_wave_cycle_behaviour.py`, `CHANGELOG.md`
  - Reads: the GH-278 changes (this todo builds on its `done` flag)
  - Depends: `GH-278`
  - Severity: medium
  - Root cause: groups and `Depends:` are parsed once and the tier loop uses that fixed list, so todos and `Depends:` edits added mid-run are silently ignored; `deriveGroupDeps` drops any `Depends:` id it cannot match, so a re-check can run alongside its fix.
  - AC (freeze): the wave file's content hash is taken after Parse and checked before each implement tier and before archive; a mismatch stops the run with error `wave-file-changed`, and no further agent is dispatched. The runner's own archive step (which edits the file) is not counted as a change.
  - AC (Depends): `Depends:` ids are backticked todo ids. TODO_SCAN_PY collects them per todo. An id that matches no todo in the file, or matches a `[~]` todo, stops the run at Parse with error `dangling-depends` naming the id. A `Depends:` on an `[x]` todo counts as met. `Depends: (none)` and an empty field are valid. Existing wave files in `workspace/todos/completed/` that use backticked ids must still parse (spot-check a few in a test fixture).
  - AC (docs): `harness/skills/wave/SKILL.md` says the wave file is frozen during a run and how to re-run; the wave-format docs give the `Depends:` id format.
  - Tests: (1) wave file edited between tiers → `wave-file-changed`, no later implementer runs; (2) `Depends:` on an unknown id → `dangling-depends` at Parse, no agent after Parse; (3) `Depends:` on a `[~]` todo → `dangling-depends`; (4) `Depends:` on an `[x]` todo → the dependent runs; (5) the archive step's own edit does not trip the freeze. Each for every runner in `RUNNERS`.
  - GH: https://github.com/wailuen/a2a-sdk/issues/279
