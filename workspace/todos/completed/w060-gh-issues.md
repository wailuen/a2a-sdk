# w060 — GitHub issues 218, 219, 221 (ruled remainders) + 222, 223

Sourced from open issues on wailuen/a2a-sdk (triage 2026-10-23). Builds on the staged, unreleased w059 changes (same 0.18.0 release).
GH-186 is deferred by ruling and NOT in this wave. GH-205/206/207/212/214 wait on rulings and are NOT in this wave. GH-224 is design-only.
Groups G1–G4 run in parallel except where a cross-group `Depends:` says otherwise: GH-218 (G2) and GH-219 (G1) wait for GH-222 (G3), because they share `docs/security.md` and `DESIGN.md`. Items inside one group share files and run in order.
Target: 0.18.0.

Every item cites its maintainer ruling URL. Implement exactly what the ruling says; anything the ruling rejects stays out.
Out of scope for every item: do NOT edit `template/` (separate repo) — except GH-223, which lists its `template/` mirror files under Creates and lands them via commit+push to wailuen/a2a-agent-template as an explicit final step. Each item adds its own entry to `CHANGELOG.md` `[Unreleased]`, pinned by a per-item `grep -n GH-<id> CHANGELOG.md` AC.

---

## G1 — MCP tool list + agent card (`agent_sdk/routes/mcp.py`, `agent_sdk/routes/agent_card.py`, `docs/tools.md`)

- [ ] `GH-221` parts 4–6: tools/list size, one-of-required docs, instructions text ‖ group:G1
  - Creates: (modifies `agent_sdk/routes/mcp.py` (`_handle_tools_list` ~558-590), `docs/tools.md`, new `tests/test_gh221_tools_list_titles.py`, `CHANGELOG.md`)
  - Reads: `agent_sdk/agent/registry.py` (`input_schema` ~679-759, output schema ~761-795), `agent_sdk/testing/mcp.py` (C-056: `McpClient.list_tools` ~114, `_has_ref` ~140, `_check_list` ~153, `DEFAULT_SIZE_BUDGET` ~36)
  - Severity: low
  - Ruling: https://github.com/wailuen/a2a-sdk/issues/221#issuecomment-6345506542
  - Root cause: Each tool's `inputSchema`/`outputSchema` on `tools/list` carries pydantic's auto-generated `title` keys on every field and model, which are noise and a large share of the 74 KB list.
  - AC: On `tools/list` only, pydantic auto-generated `title` keys are removed recursively from `inputSchema` and `outputSchema` (including inside `$defs`, `properties`, `items`, `anyOf`). A `title` that is a *property name* inside `properties` is never removed. The agent loop, the agent card and validation are unchanged (apply at the MCP call site, not in `registry.py`).
  - AC: No `$defs` sharing across tools.
  - AC: Test measures the serialized `tools/list` size on the example agent before and after and asserts it shrank; asserts no `title` key remains under any schema node; asserts a field literally named `title` survives in `properties`. The measurement reuses C-056: tools fetched with `McpClient.list_tools` over an httpx ASGI `transport=`, size computed exactly as `_check_list` does (`len(json.dumps(tools, separators=(',', ':')).encode())`), so the number matches what the Phase 1.5 acceptance gate enforces against `DEFAULT_SIZE_BUDGET`. Failing test written RED before the code, GREEN after.
  - AC: The test also runs C-056's `_has_ref` ($ref/$defs) check on the stripped schemas and states the intended behavior: either tool schemas carry no `$defs` and the check passes, or `$defs` legitimately remain and the test documents why that is not a gate failure. Title stripping must not add or remove `$defs`/`$ref`.
  - AC: `docs/tools.md` shows how an agent states "ID A or ID B" with `model_config = {"json_schema_extra": {"anyOf": [{"required": ["a"]}, {"required": ["b"]}]}}`, and a test confirms that `anyOf` reaches `tools/list` unchanged.
  - AC: Part 6 (credential names in `initialize.instructions`) is unchanged — working as intended per the ruling.
  - AC: CHANGELOG `[Unreleased]` has a line naming GH-221 under Changed (tools/list title stripping, docs/tools.md anyOf example) with the ruling URL; verified by `grep -n GH-221 CHANGELOG.md` hitting inside `[Unreleased]` (LRN-424/435/445: four groups edit this file in parallel).
  - GH: https://github.com/wailuen/a2a-sdk/issues/221
  - Reuses: C-056  # agent_sdk/testing/mcp.py: McpClient.list_tools (paginated, accepts httpx ASGI transport=) and _check_list's compact serialization measure the before/after size; _has_ref confirms stripped schemas still pass (or documents why $defs remain). Do not write a second size measurer.

- [ ] `GH-219` parts 1, 2, 4: description warning, tags docs, drop card outputSchema ‖ group:G1
  - Depends: GH-221 (same `docs/tools.md`), GH-222 (same `DESIGN.md`)
  - Creates: (modifies `agent_sdk/app.py` (boot warnings ~594-599), `agent_sdk/routes/agent_card.py` (`_skill_for` ~108-132, constants ~31-41), `agent_sdk/agent/registry.py` (`output_schema()` docstring only), `tests/test_mcp_conformance_w9.py` (RT-004 card tests ~611-650), `docs/tools.md`, `DESIGN.md` (agent card section), `workspace/todos/deferred/w050-group-G4-medium-low.md` (RT-001 status line only, if it is about card `outputSchema` drift), new `tests/test_gh219_card_remainders.py`, `CHANGELOG.md`)
  - Reads: `agent_sdk/config.py` (~91)
  - Severity: low
  - Ruling: https://github.com/wailuen/a2a-sdk/issues/219#issuecomment-6345507008
  - Root cause: (1) A blank `AGENT_DESCRIPTION` silently falls back to the display name. (2) Authors don't know about `tags=`. (4) The card repeats each tool's `outputSchema`, which MCP `tools/list` already carries; triage found no runtime SDK consumer of the card's `x-sdk.outputSchema` (only the RT-004 tests in `tests/test_mcp_conformance_w9.py`).
  - AC: Boot logs one `logger.warning` when `AGENT_DESCRIPTION` is blank, matching the empty-tags warning style. The `display_name` fallback stays. No persona-derived text, no boot failure.
  - AC: `docs/tools.md` `@tools.tool` examples show `tags=`. No SDK default tag.
  - AC: Before removing anything, grep `agent_sdk/` (routes, console static JS, testing, a2ui) for any reader of the card's `x-sdk.outputSchema` / `outputSchemaWireNote`. If one exists, stop: leave the card unchanged and record why in the CHANGELOG entry. If none: the card's skills no longer emit `x-sdk.outputSchema` or `x-sdk.outputSchemaWireNote` (and the now-unused constant goes); `x-sdk.inputSchema` stays.
  - AC: The RT-004 tests in `tests/test_mcp_conformance_w9.py` are rewritten (not deleted) to assert the card omits `outputSchema` while MCP `tools/list` still carries it, citing the ruling URL. Mark the w050 G4 RT-001 deferred item closed if it is about card `outputSchema` drift.
  - AC: Test: card byte size for the example agent shrank; CHANGELOG `[Unreleased]` lists the card change under Changed on a line naming GH-219 with the ruling URL; verified by `grep -n GH-219 CHANGELOG.md` hitting inside `[Unreleased]` (LRN-424/435/445).
  - GH: https://github.com/wailuen/a2a-sdk/issues/219

## G2 — Deploy docs

- [ ] `GH-218` template part: document forwarded-header trust (doc only) ‖ group:G2
  - Depends: GH-222 (same `docs/security.md`)
  - Creates: (modifies `docs/deployment.md`, `docs/security.md` (trusted-proxy paragraph), `CHANGELOG.md`, `tests/test_changelog_gh143_gh144_wire_changes.py` (_GRANDFATHERED_ALIASES ratchet: drop `AGENT_SDK_TRUSTED_PROXIES`, now named in CHANGELOG))
  - Reads: `agent_sdk/common/limits.py` (`client_ip` ~42-54, module docstring), `agent_sdk/config.py` (~166-168), `template/Dockerfile` (~65, read only)
  - Severity: low
  - Ruling: https://github.com/wailuen/a2a-sdk/issues/218#issuecomment-6345507574
  - Root cause: Behind a TLS gateway uvicorn trusts forwarded headers only from 127.0.0.1. The issue's `--forwarded-allow-ips='*'` lets clients spoof `request.client` and bypass the `AGENT_SDK_TRUSTED_PROXIES` rate-limit trust model.
  - AC: `docs/deployment.md` explains setting uvicorn's `FORWARDED_ALLOW_IPS` env var to the gateway's address range, using the same values as `AGENT_SDK_TRUSTED_PROXIES`, and warns never to use `*` (with the reason). It notes that w059 already serves `/mcp/` without a redirect.
  - AC: `docs/security.md` cross-links that paragraph from its trusted-proxy text.
  - AC: No code change, no `template/` change.
  - AC: CHANGELOG `[Unreleased]` has a line naming GH-218 (docs: FORWARDED_ALLOW_IPS guidance) with the ruling URL; `grep -n GH-218 CHANGELOG.md` hits inside `[Unreleased]` (LRN-424/435/445; LRN-437: CHANGELOG.md is listed in Creates, so it must land).
  - GH: https://github.com/wailuen/a2a-sdk/issues/218

## G3 — OAuth confidential DCR clients (`agent_sdk/routes/oauth.py`, `agent_sdk/auth/oauth_tokens.py`)

- [ ] `GH-222` DCR only issues public clients — opt-in client secrets for Microsoft 365 Copilot ‖ group:G3
  - Creates: (modifies `agent_sdk/routes/oauth.py` (metadata ~214, `oauth_register` ~331-391, token endpoint ~981-1038, revoke ~1045-1090, docstrings ~332-333, ~982), `agent_sdk/auth/oauth_tokens.py` (`register_client` ~160-181, client record, refresh family ~217-258, ~297-327), `docs/security.md` (~12), `DESIGN.md` (OAuth chain section ~388-389), new `tests/test_gh222_confidential_dcr.py`, `tests/test_gh152_idp_off_regression.py` (GOLDEN_METADATA authorization-server hash re-captured for the `token_endpoint_auth_methods_supported` change), `CHANGELOG.md`)
  - Reads: `harness/reference/mcp-protocol.md` (~308-311, ~338-342), `workspace/todos/completed/w012-gh-issues.md` (AC-2 ~198), `agent_sdk/console/static/mcp.js` (~280), `tests/test_rt001_client_cap_idp.py` (~66-69, read only: exact public-record key set)
  - Severity: medium
  - Ruling: https://github.com/wailuen/a2a-sdk/issues/222#issuecomment-6355272603
  - Root cause: Metadata advertises only `none`, `/oauth/register` hard-codes `token_endpoint_auth_method: "none"` and silently ignores a requested method, and `/oauth/token` authenticates by `client_id` + PKCE only. Microsoft 365 Copilot's docs say it needs a `client_secret` from DCR.
  - AC: `/oauth/register` honours `token_endpoint_auth_method` ∈ {`none`, `client_secret_post`, `client_secret_basic`}; absent → `none` (existing w012 AC-2 behavior and its test unchanged); any other value → 400 `invalid_client_metadata`.
  - AC: A confidential registration returns `client_secret` (`secrets.token_urlsafe(32)`) exactly once plus `client_secret_expires_at: 0`. The stored client record holds only the sha256 of the secret and the chosen method. The plaintext secret is never logged, stored, or echoed in errors.
  - AC: Metadata `token_endpoint_auth_methods_supported == ["none", "client_secret_post", "client_secret_basic"]`; `code_challenge_methods_supported` stays `["S256"]`.
  - AC: `/oauth/token` reads the required method from the STORED client record, never from caller input. A confidential client must present its secret through exactly its registered method (form body for post; `Authorization: Basic` for basic, with form-urldecoding of id and secret per RFC 6749 §2.3.1); comparison via `hmac.compare_digest` on hashes. Missing, wrong, or wrong-method secret → 401 `invalid_client` (with `WWW-Authenticate: Basic` for basic clients). A public client that presents a secret → `invalid_client`.
  - AC: PKCE S256 stays mandatory for confidential clients too; `consume_code` is unchanged.
  - AC: The `refresh_token` grant applies the same secret check using the client record bound to the refresh family.
  - AC: `/oauth/revoke` without a Bearer token: a confidential client must authenticate with its secret (RFC 7009 §2.1); `client_id` alone is accepted only for public clients.
  - AC: Client eviction and the one-time-consent shortcut behave the same for confidential clients.
  - AC: `docs/security.md` says plainly that open-DCR secrets are a compatibility measure, not a trust boundary; consent at `/authorize` remains the real gate. It notes the M365 requirement is from Microsoft docs and not yet validated on a live tenant. Docstrings and `DESIGN.md` updated.
  - AC: Tests: public default unchanged; confidential post and basic each complete code → token → refresh; wrong/missing/other-method secret fails on token, refresh and revoke; secret absent from logs (caplog) and from the stored record; unknown method → 400.
  - AC: Public client records keep exactly their current key set (`client_id`, `client_name`, `redirect_uris`, `token_endpoint_auth_method`, `consented`, `created_at`). The secret-hash field is written only for confidential clients — never added to public records, not even as `None`. `tests/test_rt001_client_cap_idp.py` (exact key-set assertion ~66-69) stays unchanged and green (LRN-441).
  - AC: CHANGELOG `[Unreleased]` names GH-222 under Added (confidential DCR: client_secret_post/basic, metadata change) with the ruling URL; `grep -n GH-222 CHANGELOG.md` hits inside `[Unreleased]` (LRN-424/435/445).
  - SI: SI-2, SI-5  # New secret-at-rest surface in the OAuth client store: hash only, never logged, constant-time compare, method bound to the stored record.
  - GH: https://github.com/wailuen/a2a-sdk/issues/222

## G4 — SDK-candidate re-check + opt-in auto-file (harness)

- [ ] `GH-223` auto-file SDK-level findings — re-check always, auto-file opt-in ‖ group:G4
  - Creates: (modifies `harness/workflows/wave-cycle.js` (codify SDK-candidate block ~1908-1953), `.claude/workflows/sdk-wave.js` (~1896-1933), `.claude/workflows/wave-cycle.js` (byte-identical sync of the harness copy), `harness/skills/sdk-issue-scan/SKILL.md` (Rules ~168-173), `harness/skills/sdk-issue/SKILL.md` (Rules ~191-192), `.claude/skills/sdk-issue-scan/SKILL.md`, `.claude/skills/sdk-issue/SKILL.md`, `harness/skills/wave/SKILL.md` and `.claude/skills/wave/SKILL.md` (new arg docs), `tests/test_wave_cycle_behaviour.py`, `tests/test_sdk_wave_behaviour.py`, `CHANGELOG.md`, `template/.claude/workflows/wave-cycle.js`, `template/.claude/skills/sdk-issue-scan/SKILL.md`, `template/.claude/skills/sdk-issue/SKILL.md`, `template/.claude/skills/wave/SKILL.md`)  # template/ paths: lands via commit+push to wailuen/a2a-agent-template; implementer runs `git -C template/ commit && git -C template/ push` as an explicit final step
  - Reads: `workspace/sdk-candidates.md` (w059 example, 28 candidates mostly fixed in-wave), `harness/agents/core/redteam.md` (~220, ~245), `.claude/workflows/sdk-wave.js` (C-058 `STALE_CHECK_PY` ~1350, `dropStaleFindings` ~1384, `SDK_SCAN_SCHEMA` ~272), `harness/workflows/wave-cycle.js` (C-058 ~1355-1415, `SDK_SCAN_SCHEMA` ~265), `tests/test_workflow_sync.py` (axis 2: harness ↔ template byte-identical)
  - Severity: medium
  - Ruling: https://github.com/wailuen/a2a-sdk/issues/223#issuecomment-6355273001
  - Root cause: SDK candidates are collected from each redteam round's findings before fixes run, so `sdk-candidates.md` is mostly items the same wave already fixed; filing needs a manual `/sdk-issue-scan` with one confirmation per issue.
  - AC: At codify, both runners re-check every candidate against the current tree by reusing C-058: run the existing `STALE_CHECK_PY` (same fail-closed rules as `dropStaleFindings`) on the candidates — no second checker. A candidate whose quote is found → `still-open`; whose quote is gone → `fixed-in-wave`; whose quote is empty, never verified present, or whose path is missing / grep errors / result is untrusted → `still-open`. Write `Status: fixed-in-wave | still-open` per candidate in `workspace/sdk-candidates.md`. When the wave runs in the SDK repo, findings about the wave's own process (CHANGELOG/todo-scope/template-mirror hygiene) are excluded.
  - AC: `SDK_SCAN_SCHEMA` in both runners carries the original finding `id` and `quote` through classification unchanged (the classifier may rewrite `description` but not these), so each candidate maps back to its quote for the C-058 check.
  - AC: New opt-in arg `autoFileSdkIssues` (default `false`). When `true`: files only `still-open` candidates, deduped against open issues via `gh issue list -R wailuen/a2a-sdk --search`, created with `gh issue create -R wailuen/a2a-sdk` (both commands always pass `-R`, so a run from an agent repo never targets the agent's own repo), labelled `auto-filed` plus the component label, at most 10 per run, and writes each issue URL back into `sdk-candidates.md`. If `gh` is unavailable or unauthenticated it logs and falls back to the file; the wave never fails because of filing.
  - AC: The issue title and body are built only from the classified fields (description, component, severity, file path) — never from `quote` or any code excerpt — and pass through a credential-pattern redaction (e.g. `sk-…`, `ak_…`, bearer tokens, long hex/base64 secrets) before ANY `gh` call. The dedupe `gh issue list -R wailuen/a2a-sdk --search <text>` string is built from the already-redacted title only, never from the raw description. A candidate that still matches a secret pattern after redaction is neither searched nor filed and is left in the file for manual `/sdk-issue-scan`. The body is passed with `--body-file <tmp>` (temp file, removed after), never as a `--body` argv string.
  - AC: Default (`false`) files nothing; per-issue confirmation stays the default. `sdk-issue` and `sdk-issue-scan` Rules describe the opt-in exception and keep the classification gate and the no-credentials rule.
  - AC: `.claude/workflows/wave-cycle.js` and `template/.claude/workflows/wave-cycle.js` stay byte-identical to `harness/workflows/wave-cycle.js` (`tests/test_workflow_sync.py` green). `template/.claude/skills/sdk-issue-scan/SKILL.md`, `template/.claude/skills/sdk-issue/SKILL.md`, `.claude/skills/sdk-issue-scan/SKILL.md` and `.claude/skills/sdk-issue/SKILL.md` are byte-identical to their harness copies after the change (they are byte-identical today; check with `cmp`) (LRN-314).
  - AC: `template/.claude/skills/wave/SKILL.md` already drifts from `harness/skills/wave/SKILL.md` at HEAD, unrelated to this wave (severity-floor vs zero-tolerance wording ~12-13, `agentBudget` arg doc ~72-75, Unit/Phase Redteam bullets ~83-99, Archive bullet ~103-105, ~127-133). Outcome (b): apply ONLY the GH-223 `autoFileSdkIssues` arg-doc hunk to the template copy at the matching spot; do not copy the whole file and do not fix the old drift. Same for `.claude/skills/wave/SKILL.md` (it also differs from the harness copy today): add only the GH-223 hunk. LRN-314 check for these two files: `diff` against the harness copy shows no hunk mentioning `autoFileSdkIssues`/GH-223; the remaining hunks are the known deferred drift below, not this wave's miss.
  - Deferred: pre-existing `template/.claude/skills/wave/SKILL.md` ↔ `harness/skills/wave/SKILL.md` drift (hunks listed above) is out of scope for w060; the GH-223 CHANGELOG entry states it as a known deferred item so the archive gate does not count it as this wave's miss.
  - AC: Tests (both behaviour test files), failing tests written RED before the code, GREEN after: default mode files nothing; auto mode skips `fixed-in-wave`, respects the cap, dedupes, and falls back when `gh` is missing; a candidate with an empty or unverified quote stays `still-open`; both `gh` commands carry `-R wailuen/a2a-sdk`; a candidate carrying a key-like string (`sk-…`, `ak_…`) is filed with it redacted or neither searched nor filed, `sk-`/`ak_` never appears in the argv of either `gh` command (`issue list --search` and `issue create`), the body goes via `--body-file`, and `quote` never appears in the issue body. A cross-runner parity assertion pins the candidate re-check and filing logic in sdk-wave.js and wave-cycle.js (LRN-159: sdk-wave.js is outside the byte-identical guard).
  - AC: Final step: the `template/` mirror changes land via commit+push to wailuen/a2a-agent-template (`git -C template/ commit && git -C template/ push`); the pushed commit SHA is recorded in the CHANGELOG entry. sdk-wave.js has no template copy and needs none.
  - GH: https://github.com/wailuen/a2a-sdk/issues/223
  - Reuses: C-058  # STALE_FINDING_FILTER (STALE_CHECK_PY + dropStaleFindings, sdk-wave.js ~1346-1410, mirrored in harness/workflows/wave-cycle.js) is the deterministic fail-closed re-check; carry finding id + quote through SDK_SCAN_SCHEMA so it can run on candidates. Add cross-runner parity assertions in both behaviour test files (LRN-159).
  - SI: SI-2, SI-6  # Auto-filing posts redteam finding text to a public GitHub issue with no human in the loop; in agent repos an SI-2/SI-6 finding's quote can be a hard-coded key or token. Issue body from classified fields only (never quote/code), credential-pattern redaction before gh issue create, -R wailuen/a2a-sdk on both gh commands; regression test with a key-like string.
  - SI: SI-6  # Round-1 SI-2/SI-6 items resolved. Remaining gap closed above: the dedupe `gh issue list --search` string is built from the already-redacted title; a candidate still matching a secret pattern is neither searched nor filed; body passed via `--body-file <tmp>`, not `--body` argv; the key-like-string regression test asserts 'sk-'/'ak_' never appears in either gh command's argv.

---

Archived 2026-10-23 by hand. The only red test was `test_gh164_template_mirror_is_committed_and_pushed`, which passes once wailuen/a2a-agent-template PR #2 is merged as part of the 0.18.0 release. Medium/low findings are in `workspace/todos/deferred/w060-*.md`.
