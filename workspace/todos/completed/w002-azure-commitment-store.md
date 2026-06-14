# w002 — AzureTableCommitmentStore

Parallel with W1 and W3. Depends on W0 complete (P0-00 through P0-04).
All items in group:C. Within-group order: P2-00 → P2-01 → P2-02 → P2-03 → P2-04 → P2-05.

**CRITICAL invariant:** The at-most-once claim (`claim_due`) MUST use ETag
optimistic concurrency on Azure Table Storage. Two replicas racing on the same
pending row must produce exactly one winner. This maps `rowcount==1` from SQLite
to `if_match=etag, match_condition=MatchConditions.IfNotModified` on the update.

---

- [ ] `P2-00` Implement `AzureTableCommitmentStore` core + `add()` ‖ group:C
  - Creates: `agent_sdk/contrib/commitments/azure_table.py`
  - Reads: `agent_sdk/contrib/commitments/store.py`, `agent_sdk/contrib/commitments/backend.py`
  - Depends: P0-04 (W0 complete)
  - AC: Class `AzureTableCommitmentStore(CommitmentBackend)` in `agent_sdk/contrib/commitments/azure_table.py`. Constructor accepts `connection_string: str | None`, `account_name: str | None`, `table_prefix: str = "agent"`. Table name: `{prefix}commitments` (e.g. `agentcommitments`). Calls `require_azure_packages()`. Entity schema: `PartitionKey="commitments"`, `RowKey=<uuid>`, plus columns: `tool`, `args_json`, `fire_at`, `status`, `created_at`, `identity_binding` (nullable), `auth_context_json`, `claimed_at` (nullable), `attempts` (Int32), `last_error` (nullable). `add()` — same validation logic as `CommitmentStore.add()` (secret-key refusal, `_normalize_fire_at`, `_dump_json`, `redact`) then `create_entity()`. Returns `commitment_id`.

- [ ] `P2-01` Implement `claim_due()` with ETag optimistic concurrency ‖ group:C
  - Creates: (continues `agent_sdk/contrib/commitments/azure_table.py`)
  - Reads: `agent_sdk/contrib/commitments/store.py` (claim_due contract)
  - Depends: P2-00
  - AC: `claim_due(now, limit)` — queries `"PartitionKey eq 'commitments' and status eq 'pending' and fire_at le '{now}'"` with `select=["RowKey"]`, ordered by `fire_at`, top `limit`. For each candidate: calls `get_entity(PartitionKey="commitments", RowKey=row_key)` to get fresh ETag. Attempts `update_entity(entity_with_status_firing, mode=UpdateMode.REPLACE, etag=entity.metadata["etag"], match_condition=MatchConditions.IfNotModified)`. On `ResourceModifiedError`: skips (another replica won — at-most-once preserved). On success: increments `attempts`, sets `claimed_at`. Returns list of `Commitment` dataclass instances for rows this replica won. **No two replicas can both claim the same row** — verified in test P2-04.

- [ ] `P2-02` Implement `mark_fired`, `mark_failed`, `cancel`, `reap_stale_firing`, `get`, `list`, `close` ‖ group:C
  - Creates: (continues `agent_sdk/contrib/commitments/azure_table.py`)
  - Reads: `agent_sdk/contrib/commitments/store.py`
  - Depends: P2-01
  - AC: `mark_fired(commitment_id)` — gets entity, checks `status=="firing"`, updates to `"fired"` with ETag guard; returns `True` iff won. `mark_failed(commitment_id, reason)` — same with `"failed"` and `last_error=safe_reason`; bearer-scrubs and truncates reason before persisting (same as SQLite path, SI-2). `cancel(commitment_id, identity_binding)` — gets entity, checks `status=="pending"` and binding match if given, updates to `"cancelled"` with ETag; returns bool. `reap_stale_firing(lease_seconds)` — property filter `"status eq 'firing' and claimed_at le '{cutoff}'"`, updates each to `"failed", last_error="lease_expired"` with ETag guard (ETag may be stale; catch `ResourceModifiedError` and skip — race is benign for reaping). Returns count reaped. `get(commitment_id, identity_binding)` — `get_entity` + binding check. `list(identity_binding, status, limit)` — property filter, `top=limit`, order by `created_at desc`. `close()` — no-op.
  - SI: SI-2

- [ ] `P2-03` Add factory `create_commitment_backend(settings)` ‖ group:C
  - Creates: (adds to `agent_sdk/contrib/commitments/azure_table.py` or new `agent_sdk/contrib/commitments/factory.py`)
  - Reads: `agent_sdk/config.py`, `agent_sdk/contrib/commitments/store.py`, `agent_sdk/contrib/commitments/backend.py`
  - Depends: P2-02
  - AC: `create_commitment_backend(settings: BaseAgentSettings) -> CommitmentBackend` — returns `AzureTableCommitmentStore(connection_string=..., table_prefix=settings.azure_storage_table_prefix)` if `settings.azure_storage_connection_string` set, or `AzureTableCommitmentStore(account_name=..., ...)` if `settings.azure_storage_account_name` set, or `CommitmentStore(path)` otherwise. Exported from `agent_sdk/contrib/commitments/__init__.py`. `commitments_lifespan` updated to call `create_commitment_backend(settings)` instead of hardcoding `CommitmentStore(path)` when no `CommitmentsSource` is registered.

- [ ] `P2-04` Unit tests for `AzureTableCommitmentStore` — including at-most-once race ‖ group:C
  - Creates: `tests/test_azure_commitment_store.py`
  - Reads: `tests/test_contrib_commitments.py`, `agent_sdk/contrib/commitments/azure_table.py`
  - Depends: P2-03
  - AC: Tests mock `TableServiceClient`. Cover: (1) `add()` happy path; (2) secret-in-args raises `ValueError`; (3) `claim_due()` — two concurrent callers with mock returning `ResourceModifiedError` on second update — only one caller gets the commitment in its return list; (4) `mark_fired()` returns `True` on success, `False` if entity no longer in `firing`; (5) `mark_failed()` reason is bearer-scrubbed and truncated (SI-2); (6) `cancel()` identity-binding mismatch returns `False`; (7) `reap_stale_firing()` skips entity on `ResourceModifiedError`; (8) `get()` returns `None` on missing entity; (9) `list()` filters by identity_binding and status; (10) `create_commitment_backend()` returns correct type per settings.

- [ ] `P2-05` Update `CommitmentsSource` to use `CommitmentBackend` type ‖ group:C
  - Creates: (modifies `agent_sdk/contrib/commitments/source.py`)
  - Reads: `agent_sdk/contrib/commitments/source.py`, `agent_sdk/contrib/commitments/backend.py`
  - Depends: P2-04
  - AC: `CommitmentsSource.__init__` constructs store via `create_commitment_backend(settings)` when `db_path` is `None` (Azure-aware). When `db_path` is explicitly given, falls back to `CommitmentStore(db_path)` for backward compat. `self.store: CommitmentBackend` type annotation updated. All existing `CommitmentsSource` tests pass.
