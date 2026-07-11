# Component registry

| ID | Name | Location | Status |
|----|------|----------|--------|
| C-001 | crypto | agent_sdk/credentials/crypto.py | present |
| C-002 | CommitmentBackend | agent_sdk/contrib/commitments/backend.py | present |
| C-003 | SubscriptionBackend | agent_sdk/contrib/webhooks/backend.py | present |
| C-004 | uv-lockfile-bootstrap convention | harness/reference/uv-lockfile-bootstrap.md (new) | planned |
| C-005 | TaskStore | agent_sdk/tasks/store.py | present |
| C-006 | A2uiCapabilityGate | agent_sdk/a2ui/translator.py (alongside A2uiCapabilities) | planned |
| C-007 | safe_error_text | agent_sdk/common/redact.py | planned |
| C-008 | iso_utc | agent_sdk/common/iso8601.py | present |

## Descriptions

**C-001 crypto** (`agent_sdk/credentials/crypto.py`)
Shared AES-256-GCM encryption module extracted from EncryptedSqliteStore. Exports `derive_key`, `encrypt`, `decrypt`, and `PBKDF2_ITERATIONS`. Reusable by any backend that needs authenticated symmetric encryption with namespace/field AAD binding.

**C-002 CommitmentBackend** (`agent_sdk/contrib/commitments/backend.py`)
Abstract base class extracted from CommitmentStore. Defines the public contract (`add`, `claim_due`, `mark_fired`, `mark_failed`, `cancel`, `reap_stale_firing`, `get`, `list`, `close`) so Azure Table Storage and any future durable-store implementations can be swapped without touching CommitmentExecutor or CommitmentsSource.

**C-003 SubscriptionBackend** (`agent_sdk/contrib/webhooks/backend.py`)
Abstract base class extracted from SubscriptionStore. Defines the public contract (`initialize`, `upsert`, `set_expiration`, `delete`, `get`, `list`, `due_for_renewal`, `close`) so GraphSubscriptionManager and webhooks_renewal_lifespan can accept any backing store (SQLite, Azure Tables, in-memory) via dependency injection.

**C-005 TaskStore** (`agent_sdk/tasks/store.py`)
Abstract base class for the SDK's task lifecycle store. Defines the public contract that `InMemoryTaskStore` (`agent_sdk/tasks/memory.py`) implements and that external durable-store implementations (e.g. AzureTableTaskStore) must satisfy. Key public methods: `create`, `get`, `subscribe`, `unsubscribe`, `find_interrupt`, `publish`, `close_streams`, `mark_interrupted`, `deliver_resume`, `interrupt_ttl_remaining`, `evict`, `sweep`, `close_all`, and `context_messages`. Breaking change in w022: `list_tasks_for_identity` return type changed from `tuple[list[Task], str | None]` to `tuple[list[Task], str | None, int]` — the third element is the total count of all matching tasks regardless of cursor position. External `TaskStore` subclass implementors must update their `list_tasks_for_identity` signature to match. w031/AGUI-1 (RT-002, non-breaking): added `interrupt_ttl_remaining(task_id) -> float | None`, a relative-seconds-to-expiry hook the AG-UI route now reads instead of the old absolute `record.interrupt_deadline` when serializing `Interrupt.expiresAt`. The base-class default returns `None` (unknown) so pre-existing external `TaskStore` subclasses keep instantiating without an override — but they will silently stop emitting `expiresAt` on AG-UI interrupt outcomes (previously an absolute, monotonic-clock-derived `int` was emitted; now nothing is, rather than a wrong value). External subclassers who want `expiresAt` back must override `interrupt_ttl_remaining` to compute seconds-remaining from their own store's tracked deadline and clock. Call this out explicitly in the 0.5.40 CHANGELOG entry under "Breaking/behavior changes for TaskStore subclassers".

**C-006 A2uiCapabilityGate** (`agent_sdk/a2ui/translator.py (alongside A2uiCapabilities)`)
Fail-closed per-transport A2UI capability resolver. After GH-74 lands, agent_sdk/routes/a2a.py:82-89 (_capabilities, gates on X-A2A-Extensions header) and agent_sdk/routes/ag_ui.py:315-318 (_capabilities, gates on forwardedProps.a2uiClientCapabilities) become structurally parallel: both must return A2uiCapabilities(tier='none') when the client sent no opt-in signal, and delegate to from_metadata() only when opted in. The only per-transport difference is where the opt-in signal lives. Extract a shared classmethod like A2uiCapabilities.gated(opted_in: bool, raw: Any) -> A2uiCapabilities so the fail-closed default is defined once and any future transport (or these two) cannot drift back to fail-open. Prevents recurrence of LRN-046 across transports.

**C-004 uv-lockfile-bootstrap convention** (`harness/reference/uv-lockfile-bootstrap.md (new)`)
GH-70b (setup), GH-70c (new-agent) and GH-70d (template/Dockerfile) all independently implement the same three-step convention: run `uv lock` to generate an initial uv.lock after template render, install with `uv sync --frozen` (no bare pip / no editable install), and `git add uv.lock` in the scaffold/upgrade commit. GH-70a (upgrade) re-locks the same way. This is one reusable harness convention being copied into four places, so the exact command sequence and rollback notes will drift between skills over time. Extract a single reference doc (or a shared command snippet) that all four todos point at, so the lock+frozen-install+commit recipe is defined once. Also: the template/ scaffold currently ships pyproject.toml with NO uv.lock (confirmed: template/uv.lock absent), so GH-70d's `COPY uv.lock ./` will fail at docker build unless GH-70b/GH-70c actually generate and commit template/uv.lock first — the four todos share an implicit ordering/artifact dependency on the committed lockfile that the group:G 'all independent' framing hides.

**C-007 safe_error_text** (`agent_sdk/common/redact.py`)
Shared truncate+control-char-strip helper for building error messages from untrusted (model-/caller-supplied) strings, guarding SI-2 log/wire injection. The pattern is currently inline at loop.py:392 (`tc.name[:64].translate(dict.fromkeys(range(0x20), " "))`); GH-99 copies it verbatim to loop.py:372 and GH-96's run_error path needs the same guarantee — a third and fourth divergent copy. The existing `agent_sdk/common/redact.py` only masks secret-named keys/bearer values, not control chars, so it does not cover this. Extract one helper next to `redact()` and have loop.py (load_skill + unknown-tool branches) and ag_ui.py route it, so the truncation/strip contract is defined once and cannot drift across transports.

**C-008 iso_utc** (`agent_sdk/common/iso8601.py`)
Shared ISO-8601 UTC `...Z` fixed-width timestamp formatter (RT-002). Accepts either a POSIX timestamp (`float`/`int`) or a `datetime` (naive treated as UTC, aware converted to UTC). Extracted after the `...strftime("%Y-%m-%dT%H:%M:%SZ")` idiom was found independently re-inlined 7 times: `agent_sdk/routes/ag_ui.py` (interrupt `expiresAt`, via `datetime.fromtimestamp`), `agent_sdk/contrib/commitments/store.py` (`_utcnow_iso`, `_normalize_fire_at`, `reap_stale_firing` cutoff), `agent_sdk/contrib/commitments/azure_table.py` (`reap_stale_firing` cutoff), `agent_sdk/contrib/commitments/source.py` (`_reject_non_future`, a 7th copy the originating redteam scan missed), `agent_sdk/contrib/webhooks/azure_table.py` (`_iso`), and `agent_sdk/contrib/webhooks/subscriptions.py` (`_iso`). All seven now route through `iso_utc`. Any new code that needs to format a UTC instant for the wire or for durable storage MUST call `iso_utc` rather than re-inlining `strftime("%Y-%m-%dT%H:%M:%SZ")`.
