# w004 — Wire auto-detection + migrate-store CLI

Sequential wave. Depends on W1 + W2 + W3 all complete.
Items must execute in order: P4-00 → P4-01 → P4-02 → P4-03 → P4-04 → P4-05 → P4-06.
Within the wave, later items depend on earlier ones.

---

- [ ] `P4-00` Update `Agent._build_credential_store()` in `app.py` to auto-detect Azure ‖ group:F
  - Creates: (modifies `agent_sdk/app.py`)
  - Reads: `agent_sdk/app.py`, `agent_sdk/config.py`, `agent_sdk/credentials/azure_table.py`, `agent_sdk/credentials/encrypted_sqlite.py`
  - Depends: W1 complete (P1-05), W2 complete (P2-05), W3 complete (P3-04)
  - SI: SI-6
  - AC: `Agent._build_credential_store()` logic: if `settings.azure_storage_connection_string` is set → `AzureTableCredentialStore(connection_string=settings.azure_storage_connection_string.get_secret_value(), table_prefix=settings.azure_storage_table_prefix, master_key=master_key)`. Else if `settings.azure_storage_account_name` is set → `AzureTableCredentialStore(account_name=settings.azure_storage_account_name, table_prefix=settings.azure_storage_table_prefix, master_key=master_key)`. Else → existing `EncryptedSqliteStore(db_path, master_key)` (unchanged). `connection_string.get_secret_value()` is called; the raw string is never stored in a local variable whose name ends in `_string` in a way that would appear in any log or repr (SI-6). The import of `AzureTableCredentialStore` is conditional (lazy, inside the `if` branch) so the package is not required when not configured.

- [ ] `P4-01` Update `commitments_lifespan` to use `create_commitment_backend` ‖ group:F
  - Creates: (modifies `agent_sdk/contrib/commitments/executor.py`)
  - Reads: `agent_sdk/contrib/commitments/executor.py`, `agent_sdk/contrib/commitments/factory.py`
  - Depends: P4-00
  - AC: `commitments_lifespan` — when `source is None` (executor-only path), calls `create_commitment_backend(settings)` instead of `CommitmentStore(path)`. When `db_path` kwarg is explicitly passed to `commitments_lifespan`, it is forwarded to `CommitmentStore(db_path)` for backward compat (overrides auto-detection). Existing lifespan tests pass. New test: with `AZURE_STORAGE_CONNECTION_STRING` set in settings, `commitments_lifespan` sets `app.state.commitment_store` to an `AzureTableCommitmentStore` instance (mocked).

- [ ] `P4-02` Update `webhooks_renewal_lifespan` wiring note + type annotation ‖ group:F
  - Creates: (modifies `agent_sdk/contrib/webhooks/subscriptions.py`)
  - Reads: `agent_sdk/contrib/webhooks/subscriptions.py`, `agent_sdk/contrib/webhooks/backend.py`
  - Depends: P4-01
  - AC: `GraphSubscriptionManager.__init__` type signature updated: `store: SubscriptionBackend` (was `store: SubscriptionStore`). `webhooks_renewal_lifespan` docstring updated to note that `manager._store` must be a `SubscriptionBackend` implementation. No behavioral change — only type annotation and doc update. All existing webhook tests pass.

- [ ] `P4-03` Implement `_cmd_migrate_store` in `agent_sdk/__main__.py` ‖ group:F
  - Creates: (modifies `agent_sdk/__main__.py`)
  - Reads: `agent_sdk/__main__.py`, `agent_sdk/credentials/encrypted_sqlite.py`, `agent_sdk/credentials/azure_table.py`, `agent_sdk/contrib/commitments/store.py`, `agent_sdk/contrib/commitments/azure_table.py`, `agent_sdk/contrib/webhooks/subscriptions.py`, `agent_sdk/contrib/webhooks/azure_table.py`
  - Depends: P4-02
  - SI: SI-6
  - AC: New subcommand `migrate-store` registered in `main()`. Arguments: `--data-dir` (default `./data`), `--dry-run` (print what would be migrated, no writes), `--force` (overwrite existing Table Storage entries). `_cmd_migrate_store(args)` logic: (1) load settings from env (requires `AZURE_STORAGE_CONNECTION_STRING` or `AZURE_STORAGE_ACCOUNT_NAME`; exits 1 with clear message if neither set); (2) for each SQLite store present in `data_dir` (credentials.db, commitments.db, webhook_subscriptions.db), open it read-only; (3) open corresponding Azure backend; (4) iterate rows, write to Azure (skip on collision unless `--force`); (5) print counts: `credentials migrated: N`, `pending commitments migrated: N`, `subscriptions migrated: N`. Connection string never printed (SI-6). `--dry-run` prints `[dry-run]` prefix on each row that would be migrated.

- [ ] `P4-04` Unit tests for `migrate-store` CLI ‖ group:F
  - Creates: `tests/test_migrate_store.py`
  - Reads: `agent_sdk/__main__.py`
  - Depends: P4-03
  - AC: Tests use `tmp_path` for SQLite sources and mock Azure backends. Cover: (1) `--dry-run` makes zero writes to Azure mocks but prints correct counts; (2) without `--force`, existing Azure entity is skipped; (3) with `--force`, existing Azure entity is overwritten; (4) missing `data_dir` exits cleanly with count 0 per store; (5) no Azure env vars set → exits 1 with readable message, no traceback; (6) credentials migration preserves ciphertext (plaintext is decrypted from SQLite, re-encrypted for Azure using same MASTER_KEY and shared crypto module — NOT stored as plaintext at any point in the migration path) (SI-4); (7) commitment migration only migrates `status=pending` rows (fired/failed rows are historical, not operationally needed).

- [ ] `P4-05` End-to-end integration test: `Agent.build_app()` with mocked Azure credential store ‖ group:F
  - Creates: `tests/test_app_azure_wire.py`
  - Reads: `tests/conftest.py`, `agent_sdk/app.py`
  - Depends: P4-04
  - AC: Test constructs `BaseAgentSettings(DEV_MODE=True, AZURE_STORAGE_CONNECTION_STRING="DefaultEndpointsProtocol=https;AccountName=devtest;AccountKey=dGVzdA==;EndpointSuffix=core.windows.net", ...)` with Azure table client mocked via `unittest.mock.patch`. `Agent.build_app()` completes without error. `app.state.credential_store` is an `AzureTableCredentialStore` instance. Basic lifespan startup and shutdown cycle completes (via `app.router.lifespan_context(app)`). A `settings.master_key` mismatch check value raises `AgentError(AUTH)` with no key material in message (SI-4).

- [ ] `P4-06` Verify `WEB_CONCURRENCY > 1` validator comment updated for Azure ‖ group:F
  - Creates: (modifies `agent_sdk/config.py`)
  - Reads: `agent_sdk/config.py`
  - Depends: P4-05
  - AC: The `_deployment_invariants` validator comment that says "the task store, SSE queues and rate limiter are process-local" is updated to add: "With Azure Table Storage backends for credential/commitment/subscription stores, multi-replica deployments are supported; WEB_CONCURRENCY > 1 remains unsupported within a single process (uvicorn worker model). Use Azure Container Apps replicas instead." The hard `ValueError` for `WEB_CONCURRENCY > 1` remains unchanged (it guards the in-process task store, not the persistence stores).
