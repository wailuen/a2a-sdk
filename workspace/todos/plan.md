# Plan — Azure Table Storage backends (0.4.0)

## Goal

Replace all three SQLite persistence stores with Azure Table Storage backends
so Azure Container Apps agents can run multiple replicas without losing
credential or operational state on restart. Azure Files mounts (currently
the broken workaround) are completely eliminated.

## Stores migrated

| Store | SQLite class | Azure class | ABC needed |
|-------|-------------|-------------|------------|
| CredentialStore | `EncryptedSqliteStore` | `AzureTableCredentialStore` | already exists (`CredentialStore`) |
| CommitmentStore | `CommitmentStore` (concrete) | `AzureTableCommitmentStore` | extract `CommitmentBackend` |
| SubscriptionStore | `SubscriptionStore` (concrete) | `AzureTableSubscriptionStore` | extract `SubscriptionBackend` |

## Wave summary

| Wave | File | Parallel group | Slices | Depends |
|------|------|---------------|--------|---------|
| W0 ✅ 2026-06-14 | w000-scaffold.md | sequential | 5 | — |
| W1 ✅ 2026-06-14 | w001-azure-credential-store.md | B (parallel with W2,W3) | 6 | W0 complete |
| W2 ✅ 2026-06-14 | w002-azure-commitment-store.md | C (parallel with W1,W3) | 6 | W0 complete |
| W3 ✅ 2026-06-14 | w003-azure-subscription-store.md | D (parallel with W1,W2) | 5 | W0 complete |
| W4 ✅ 2026-06-14 | w004-wire-migrate.md | sequential | 7 | W1+W2+W3 complete |
| W5 ✅ 2026-06-14 | w005-template-docs.md | E (parallel within) | 6 | W4 complete |

**Total:** 6 waves, 35 slices

---

# Plan — Protocol bug fixes (0.4.1)

## Goal

Fix 5 protocol conformance bugs surfaced by downstream agents after the 0.4.0 release (GH issues #4–#8). All 5 are independent file-level changes; they can be implemented in a single parallel wave.

## Issues

| Issue | Severity | Component | Root cause summary |
|-------|----------|-----------|-------------------|
| #4 | High | `routes/mcp.py` | `Mcp-Protocol-Version` response header on `initialize` returns default (`2025-03-26`), not the negotiated version from the body |
| #5 | Medium | `routes/agent_card.py` | `x-agui.customEvents` is a flat `string[]`; `valueSchema` missing |
| #6 | High | `agent/runner.py` | `ContentModel` artifacts emit only `TextPart`; `DataPart` never emitted unless A2UI extension activated by client (A2A §D3 violation) |
| #7 | Medium | `auth/middleware.py` | `resource_metadata` in `WWW-Authenticate` only set for `/mcp`; all other 401s return bare `Bearer realm="agent"` |
| #8 | Medium | `common/cors.py` | `Access-Control-Expose-Headers` absent from OPTIONS 204 preflight; blocks browser OAuth discovery |

## Wave summary

| Wave | File | Parallel group | Slices | Depends |
|------|------|----------------|--------|---------|
| W6 ✅ 2026-06-14 | w006-protocol-bugfixes.md | F (all parallel) | 5 | — |
| W15 [x] ✅ 2026-06-17 | w015-gh-issues.md | A+B | 4 | — |
| W16 [x] ✅ 2026-06-17 | w016-gh-issues.md | A+B+C | 7 | — |
| W17 [x] ✅ 2026-06-17 | w017-gh-issues.md | G | 2 | — |
| W18 [x] ✅ 2026-06-18 | w018-gh-issues.md | G | 1 | — |
| W19 [x] ✅ 2026-06-18 (GH-66 carved → W19b, closed 2026-06-18) | w019-gh-issues.md | G | 6 | — |
| W19b [x] ✅ 2026-06-18 GH-66 --from-github gitignore gap | w019b-gh66-reopened.md | G | 1 | — |
| W20 [x] ✅ 2026-06-18 | w020-gh-issues.md | G | 4 | — |
| W20b [x] ✅ 2026-06-20 | w020b-workflow-hardening.md | G | 3 | W20 |
| W22 [x] ✅ 2026-06-20 | w022-gh-issues.md | G | 5 | — |
| W23 [x] ✅ 2026-06-20 (GH-78/79/81/83/84) | w023-gh-issues.md | G | 5 | — |
| W24 [x] ✅ 2026-06-21 (GH-86) | w024-gh-issues.md | G | 1 | — |
| W25 [x] ✅ 2026-06-21 (GH-87, GH-88, GH-89) | w025-gh-issues.md | G+H | 3 | — |
| W26 [x] ✅ 2026-06-22 (GH-90, GH-91) | w026-gh-issues.md | G | 2 | — |
| W27 [x] ✅ 2026-06-24 (GH-92, GH-93) | w027-gh-issues.md | G | 2 | — |
| W28 [x] ✅ 2026-06-24 (GH-94) | w028-gh-issues.md | G | 1 | — |
| W29 [x] ✅ 2026-07-10 (GH-95–GH-101) | w029-gh-issues.md | G | 7 | — |
| W30 [x] ✅ 2026-07-11 (GH-104, GH-105) | w030-gh-issues.md | G | 2 | — |
| W31 [x] ✅ 2026-07-11 (AGUI-1, AGUI-2, AGUI-3) | w031-ag-ui-wire-fidelity.md | G | 2 | — |
| W32 [x] ✅ 2026-07-14 (GH-110–GH-114) | w032-gh-issues.md | G | 5 | — |
| W33 [x] ✅ 2026-07-14 (GH-115–GH-117) | w033-gh-issues.md | G | 3 | — |
| W34 [x] ✅ 2026-07-14 (GH-119–GH-121; RT-001/RT-002 group-G budget-exhausted findings fixed) | w034-gh-issues.md | G | 4 | — |
| W35 [x] ✅ 2026-07-19 (GH-118, GH-122; target 0.5.42) | w035-gh-issues.md | G | 2 | — |
| W36 [x] ✅ 2026-07-24 (GH-123 AUTH_SURFACE reconciliation; landed on main v0.5.44, commit 376f6cc) | completed/w036-gh-issues.md | G | 1 | — |
| W39 [x] ✅ 2026-08-16 (GH-129–GH-139; renamed from W36 per RT-004 — the original id collided with the completed W36 row above, whose archive `mv` would have overwritten it) | completed/w039-gh-issues.md | G | 8 | — |
| W59 [x] ✅ 2026-10-23 (GH-204B, GH-208–GH-211, GH-213, GH-215–GH-221 partial/whole; archived by hand — wave gate blocked only on template PR #2 merge, which pairs with the 0.18.0 release) | completed/w059-gh-issues.md | G | 13 | — |
| W60 [x] ✅ 2026-10-23 (GH-218 docs, GH-219 parts 1/2/4, GH-221 parts 4–6, GH-222, GH-223; archived by hand — wave gate blocked only on template PR #2 merge, which pairs with the 0.18.0 release) | completed/w060-gh-issues.md | G | 5 | — |
| W61 [x] ✅ 2026-10-23 (GH-225 multi-type emits, GH-228 scope-scan hardening; archived by hand after a release-gate MCP fix for LRN-469) | completed/w061-gh-issues.md | G | 2 | — |
| W62 [x] ✅ 2026-10-24 (GH-205 mcp_skills, GH-206 strict schema mode, GH-207 mcp_description, GH-212 id-safe text, GH-214 no deleteSurface, GH-229 acceptance args, GH-230 SafeValueError, GH-231 API docs gated; archived by hand after G1 budget stop) | completed/w062-gh-issues.md | G | 8 | — |
| W63 [x] ✅ 2026-10-24 (GH-233 acceptance-api.js parse fix + workflow parse test, GH-234 AG-UI test client; archived by hand) | completed/w063-gh-issues.md | G | 2 | — |
| W64 [x] ✅ 2026-10-24 (GH-235 ingress depth cap + AG-UI resume, GH-236 load_skill, GH-237 test clients, GH-238/239 console, GH-240 A2A catalog negotiation, GH-241 safe errors, GH-242 test fixes; archived by hand) | completed/w064-gh-issues.md | G | 8 | — |
| W65 [x] ✅ 2026-10-24 (GH-243/244 console, GH-245 test clients, GH-246 MCP body cap + id checks, GH-247 AG-UI resume validation, GH-248 A2A route, GH-249 A2UI gating, GH-250 core ingress + bidi safe text; archived by hand) | completed/w065-gh-issues.md | G | 8 | — |
| W66 [x] ✅ 2026-10-25 (GH-251 ingress, GH-252 docs/lock, GH-253 regression tests, GH-254/255 console, GH-256 test clients, GH-257 single A2UI gate, GH-258 catalog, GH-259 A2A route, GH-260 rate limit; /sdk-autoloop cycle 1, archived by hand) | completed/w066-gh-issues.md | G | 10 | — |
| W67 [x] ✅ 2026-10-25 (GH-261 A2UI per-request decision, GH-262 catalog wire rules, GH-263 console, GH-264 test helpers, GH-265 failed-bearer limiter, GH-266 error-code mapping, GH-267 cleanup; /sdk-autoloop cycle 2, archived by hand) | completed/w067-gh-issues.md | G | 7 | — |
| W68 [x] ✅ 2026-10-26 (GH-268 test helpers, GH-269 AG-UI text scrub + console caps, GH-270 A2UI reserved data_types + catalog, GH-271 A2A echo/mimeType/docs, GH-272 failed-bearer 429 challenge, GH-273 MCP session version, GH-274 example/tests/registry; /sdk-autoloop cycle 3, archived by hand) | completed/w068-gh-issues.md | G | 7 | — |

## Dependency graph

```
W0 (scaffold)
 ├─▶ W1 (credential store) ─┐
 ├─▶ W2 (commitment store)  ├─▶ W4 (wire + migrate CLI) ─▶ W5 (docs)
 └─▶ W3 (subscription store)┘
```

## Security invariants covered

| SI | Scope |
|----|-------|
| SI-4 | AzureTableCredentialStore.get() never exposes plaintext in exceptions or logs |
| SI-6 | AZURE_STORAGE_CONNECTION_STRING treated as `SecretStr`; never logged; .env.example marks it secret |
| Encryption | AES-256-GCM envelope preserved end-to-end; plaintext never written to Table Storage |
| MASTER_KEY | Same min-32-char requirement enforced in Azure path as SQLite path |

## Optional dependency

`pyproject.toml` `[azure]` extra: `azure-data-tables>=12.5`, `azure-identity>=1.15`.
Clear `ImportError` at module load if Azure backend configured but packages absent.

## Auto-detection logic (app.py)

```
AZURE_STORAGE_CONNECTION_STRING set → AzureTableCredentialStore(connection_string=...)
AZURE_STORAGE_ACCOUNT_NAME set     → AzureTableCredentialStore(account_name=...) via DefaultAzureCredential
Neither                            → EncryptedSqliteStore (dev default, unchanged)
```

Same logic exposed as `create_commitment_backend(settings)` and
`create_subscription_backend(settings)` factory functions in contrib modules.

## New settings fields (BaseAgentSettings)

| Field | Alias | Type | Default |
|-------|-------|------|---------|
| `azure_storage_connection_string` | `AZURE_STORAGE_CONNECTION_STRING` | `SecretStr \| None` | `None` |
| `azure_storage_account_name` | `AZURE_STORAGE_ACCOUNT_NAME` | `str \| None` | `None` |
| `azure_storage_table_prefix` | `AZURE_STORAGE_TABLE_PREFIX` | `str` | `"agent"` |

## Migrate CLI

`python -m agent_sdk migrate-store [--data-dir ./data] [--dry-run] [--force]`

Implemented in `agent_sdk/__main__.py` as `_cmd_migrate_store()`.
