# w001 — AzureTableCredentialStore

Parallel with W2 and W3. Depends on W0 complete (P0-00 through P0-04).
All items in group:B. Within-group order: P1-00 → P1-01 → P1-02 → P1-03 → P1-04 → P1-05.

---

- [ ] `P1-00` Implement `AzureTableCredentialStore` core class ‖ group:B
  - Creates: `agent_sdk/credentials/azure_table.py`
  - Reads: `agent_sdk/credentials/store.py`, `agent_sdk/credentials/crypto.py`, `agent_sdk/credentials/encrypted_sqlite.py`
  - Depends: P0-04 (W0 complete)
  - SI: SI-4, SI-6
  - AC: Class `AzureTableCredentialStore(CredentialStore)` in `agent_sdk/credentials/azure_table.py`. Constructor accepts either `connection_string: str` OR `account_name: str` (not both; raises `ValueError` for both/neither). Calls `require_azure_packages()` at top of `__init__`. Uses `azure.data.tables.TableServiceClient` to create-or-get table named `{prefix}credentials` (default `agentcredentials`). Salt entity stored at `PartitionKey="__meta__"`, `RowKey="salt"`, `Value=<hex-encoded 16 bytes>`. Check value stored at `PartitionKey="__meta__"`, `RowKey="check"`, `Value=<base64 ciphertext>`. `_derive_key()` reads salt from table (upserts a fresh one if absent, same as SQLite path). `_verify_master_key()` same logic as SQLite: write check on first open, verify on subsequent opens, raise `AgentError(AUTH, ...)` on mismatch — message never mentions the key value.

- [ ] `P1-01` Implement `get`, `set`, `delete`, `list_fields` methods ‖ group:B
  - Creates: (continues `agent_sdk/credentials/azure_table.py`)
  - Reads: `agent_sdk/credentials/encrypted_sqlite.py`
  - Depends: P1-00
  - SI: SI-4
  - AC: `get(namespace, field)` — gets entity `PartitionKey=namespace, RowKey=field`; returns `_decrypt(namespace, field, entity["Value"])` or `None` if not found. `set(namespace, field, value)` — calls `_encrypt(namespace, field, value)` then upserts entity with `merge_entity` (merge semantics). `delete(namespace, field)` — calls `delete_entity(partition_key=namespace, row_key=field)`, swallows `ResourceNotFoundError`. `list_fields(namespace)` — queries `"PartitionKey eq '{namespace}'"`, returns sorted list of `RowKey` values. `close()` — no-op (azure-data-tables client is stateless; method exists to satisfy `CredentialStore` ABC).

- [ ] `P1-02` Implement 5-minute TTL in-memory read cache ‖ group:B
  - Creates: (continues `agent_sdk/credentials/azure_table.py`)
  - Reads: `agent_sdk/credentials/encrypted_sqlite.py`
  - Depends: P1-01
  - AC: `_cache: dict[tuple[str,str], tuple[str, float]]` maps `(namespace, field)` to `(plaintext, expires_at)`. `get()` checks cache first; on hit returns cached plaintext if `time.monotonic() < expires_at`. On miss, fetches from Table Storage and populates cache with `expires_at = time.monotonic() + 300`. `set()` calls `_cache.pop((namespace, field), None)` before upsert (invalidate on write). `delete()` calls `_cache.pop((namespace, field), None)` before delete. `list_fields()` is NOT cached (admin operation; correctness over latency). Cache is instance-local (per-replica). Thread-safety: a `threading.Lock` wraps all cache reads/writes (same pattern as `EncryptedSqliteStore`).

- [ ] `P1-03` Add `AzureTableCredentialStore` to credentials `__init__` exports ‖ group:B
  - Creates: (modifies `agent_sdk/credentials/__init__.py`)
  - Reads: `agent_sdk/credentials/__init__.py`
  - Depends: P1-02
  - AC: `agent_sdk/credentials/__init__.py` exports `AzureTableCredentialStore` alongside `CredentialStore`. Import is a lazy conditional: `try: from .azure_table import AzureTableCredentialStore except ImportError: pass` so the package still imports cleanly when `azure-data-tables` is not installed. Test: `from agent_sdk.credentials import CredentialStore` works without azure packages installed.

- [ ] `P1-04` Unit tests for `AzureTableCredentialStore` ‖ group:B
  - Creates: `tests/test_azure_credential_store.py`
  - Reads: `tests/test_contrib_commitments.py`, `agent_sdk/credentials/azure_table.py`
  - Depends: P1-03
  - SI: SI-4, SI-6
  - AC: Tests use `unittest.mock.MagicMock` to stub `TableServiceClient` and `TableClient` — no live Azure calls. Cover: (1) get/set/delete/list_fields happy path round-trips; (2) `get()` returns `None` for missing entity; (3) cache hit avoids second Table Storage call within TTL; (4) cache invalidated on `set()`; (5) wrong MASTER_KEY raises `AgentError(AUTH, ...)` with no key material in the message (SI-4); (6) `connection_string` path and `account_name` path both instantiate correctly; (7) both-set raises `ValueError`; (8) `InvalidTag` on decrypt raises `AgentError(INTERNAL, ...)` — no ciphertext in message; (9) `close()` is a no-op that doesn't raise.

- [ ] `P1-05` Integration smoke test: CredentialStore ABC contract ‖ group:B
  - Creates: (adds to `tests/test_azure_credential_store.py`)
  - Reads: `agent_sdk/credentials/store.py`
  - Depends: P1-04
  - AC: A parameterized pytest fixture runs the same get/set/delete/list_fields contract test against both `EncryptedSqliteStore` (tmp_path) and a fully-mocked `AzureTableCredentialStore`. Both pass identically. Confirms ABC substitutability without live Azure.
