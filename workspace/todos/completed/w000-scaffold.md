# w000 — Scaffold: ABCs, crypto module, pyproject dep

Sequential wave. Every other wave depends on these items being complete.
All items in group:A; within-group order is P0-00 → P0-01 → P0-02 → P0-03 → P0-04.

---

- [ ] `P0-00` Extract `CommitmentBackend` ABC from `CommitmentStore` ‖ group:A
  - Creates: `agent_sdk/contrib/commitments/backend.py`
  - Reads: `agent_sdk/contrib/commitments/store.py`, `agent_sdk/contrib/commitments/executor.py`, `agent_sdk/contrib/commitments/source.py`
  - AC: `CommitmentBackend` is an `abc.ABC` with abstract methods matching every public method of `CommitmentStore` (`add`, `claim_due`, `mark_fired`, `mark_failed`, `cancel`, `reap_stale_firing`, `get`, `list`, `close`). `CommitmentStore` subclasses `CommitmentBackend`. `CommitmentExecutor.__init__` type annotation updated to accept `CommitmentBackend`. `CommitmentsSource.store` type updated to `CommitmentBackend`. All existing tests pass unmodified.

- [ ] `P0-01` Extract `SubscriptionBackend` ABC from `SubscriptionStore` ‖ group:A
  - Creates: `agent_sdk/contrib/webhooks/backend.py`
  - Reads: `agent_sdk/contrib/webhooks/subscriptions.py`
  - Depends: P0-00 (sequential pattern established)
  - AC: `SubscriptionBackend` is an `abc.ABC` with abstract methods matching every public method of `SubscriptionStore` (`initialize`, `upsert`, `set_expiration`, `delete`, `get`, `list`, `due_for_renewal`, `close`). `SubscriptionStore` subclasses `SubscriptionBackend`. `GraphSubscriptionManager.__init__` type annotation updated to accept `SubscriptionBackend`. `webhooks_renewal_lifespan` internal `_renew_due` uses `SubscriptionBackend`. All existing tests pass unmodified.

- [ ] `P0-02` Extract shared AES-256-GCM crypto module ‖ group:A
  - Creates: `agent_sdk/credentials/crypto.py`
  - Reads: `agent_sdk/credentials/encrypted_sqlite.py`
  - Depends: P0-01
  - AC: `crypto.py` exports `derive_key(master_key: str, salt: bytes) -> bytes`, `encrypt(aes: AESGCM, namespace: str, field: str, value: str) -> bytes` (base64 nonce+ciphertext), `decrypt(aes: AESGCM, namespace: str, field: str, blob: bytes) -> str` (raises `AgentError(INTERNAL, ...)` on `InvalidTag` — never echoes blob). `EncryptedSqliteStore` refactored to import from `crypto.py`; all existing credential store tests pass. `PBKDF2_ITERATIONS = 600_000` constant lives in `crypto.py` and is re-exported from `encrypted_sqlite.py` for `rotate.py` backward compat.

- [ ] `P0-03` Add `[azure]` optional dependency to `pyproject.toml` ‖ group:A
  - Creates: (modifies `pyproject.toml`)
  - Reads: `pyproject.toml`
  - Depends: P0-02
  - AC: `[project.optional-dependencies]` gains `azure = ["azure-data-tables>=12.5", "azure-identity>=1.15"]`. A helper `agent_sdk/contrib/azure_utils.py` exports `require_azure_packages()` that raises `ImportError` with a human-readable install hint (`pip install agent-sdk[azure]`) if either package is absent; this function is called at the top of every Azure backend `__init__` (not at module import). `pyproject.toml` parses correctly with `python -c "import tomllib; ..."`.

- [ ] `P0-04` Add Azure settings fields to `BaseAgentSettings` ‖ group:A
  - Creates: (modifies `agent_sdk/config.py`)
  - Reads: `agent_sdk/config.py`
  - Depends: P0-03
  - AC: `BaseAgentSettings` gains three new fields: `azure_storage_connection_string: SecretStr | None = Field(default=None, alias="AZURE_STORAGE_CONNECTION_STRING")`, `azure_storage_account_name: str | None = Field(default=None, alias="AZURE_STORAGE_ACCOUNT_NAME")`, `azure_storage_table_prefix: str = Field(default="agent", alias="AZURE_STORAGE_TABLE_PREFIX")`. A `@model_validator(mode="after")` raises `ValueError` if both `azure_storage_connection_string` and `azure_storage_account_name` are set (ambiguous auth). Existing settings tests pass. `connection_string` is `SecretStr` so pydantic never serializes its value into repr/logs (SI-6).
  - SI: SI-6
