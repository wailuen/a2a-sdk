# w003 — AzureTableSubscriptionStore

Parallel with W1 and W2. Depends on W0 complete (P0-00 through P0-04).
All items in group:D. Within-group order: P3-00 → P3-01 → P3-02 → P3-03 → P3-04.

---

- [ ] `P3-00` Implement `AzureTableSubscriptionStore` core + `upsert()` ‖ group:D
  - Creates: `agent_sdk/contrib/webhooks/azure_table.py`
  - Reads: `agent_sdk/contrib/webhooks/subscriptions.py`, `agent_sdk/contrib/webhooks/backend.py`
  - Depends: P0-04 (W0 complete)
  - AC: Class `AzureTableSubscriptionStore(SubscriptionBackend)` in `agent_sdk/contrib/webhooks/azure_table.py`. Constructor accepts `connection_string: str | None`, `account_name: str | None`, `table_prefix: str = "agent"`. Table name: `{prefix}subscriptions` (e.g. `agentsubscriptions`). Calls `require_azure_packages()`. Entity schema: `PartitionKey="subscriptions"`, `RowKey=<subscription_id GUID>`, plus columns: `resource`, `change_type`, `notification_url`, `lifecycle_url` (nullable), `expiration`, `client_state_ref`, `created_at`, `extra_json`. `initialize()` — no-op (Azure Table Storage auto-creates table on first write; or call `create_table_if_not_exists()`). `upsert()` — validates extra_json size (same 16 KB cap), calls `upsert_entity(mode=UpdateMode.MERGE)`. Merge semantics means partial updates don't wipe unset columns.

- [ ] `P3-01` Implement `set_expiration`, `delete`, `get`, `list`, `due_for_renewal`, `close` ‖ group:D
  - Creates: (continues `agent_sdk/contrib/webhooks/azure_table.py`)
  - Reads: `agent_sdk/contrib/webhooks/subscriptions.py`
  - Depends: P3-00
  - AC: `set_expiration(id, expiration)` — gets entity, checks exists, upserts with updated `expiration` field using MERGE; returns `True` iff entity existed. `delete(id)` — `delete_entity`, swallows `ResourceNotFoundError`. `get(id)` — `get_entity` + `_row()` deserialization; `None` on `ResourceNotFoundError`. `list()` — `query_entities("PartitionKey eq 'subscriptions'")`, ordered by `expiration`; returns `list[dict]`. `due_for_renewal(before_iso)` — `query_entities("PartitionKey eq 'subscriptions' and expiration le '{before_iso}'")`; returns `list[dict]` ordered by `expiration`. `close()` — no-op. `_row(entity) -> dict` deserializes entity fields, parses `extra_json` same as `SubscriptionStore._row()`.

- [ ] `P3-02` Add factory `create_subscription_backend(settings)` ‖ group:D
  - Creates: (adds to `agent_sdk/contrib/webhooks/azure_table.py` or new `agent_sdk/contrib/webhooks/factory.py`)
  - Reads: `agent_sdk/config.py`, `agent_sdk/contrib/webhooks/backend.py`
  - Depends: P3-01
  - AC: `create_subscription_backend(settings: BaseAgentSettings) -> SubscriptionBackend` — returns `AzureTableSubscriptionStore(connection_string=..., table_prefix=settings.azure_storage_table_prefix)` if connection_string set, or `AzureTableSubscriptionStore(account_name=..., ...)` if account_name set, or `SubscriptionStore(path)` otherwise. Exported from `agent_sdk/contrib/webhooks/__init__.py`. `webhooks_renewal_lifespan` internal comment updated to note that `manager._store` must be a `SubscriptionBackend`.

- [ ] `P3-03` Unit tests for `AzureTableSubscriptionStore` ‖ group:D
  - Creates: `tests/test_azure_subscription_store.py`
  - Reads: `tests/test_contrib_webhooks.py`, `agent_sdk/contrib/webhooks/azure_table.py`
  - Depends: P3-02
  - AC: Tests mock `TableServiceClient`. Cover: (1) `upsert()` happy path — merge semantics call confirmed; (2) `upsert()` extra_json over 16 KB raises `AgentError(VALIDATION, ...)`; (3) `set_expiration()` returns `True` on existing id, `False` on missing; (4) `delete()` on missing id does not raise; (5) `get()` returns `None` on missing; (6) `list()` returns all entities ordered by expiration; (7) `due_for_renewal(before_iso)` returns only entities with `expiration <= before_iso`; (8) `create_subscription_backend()` returns correct type per settings; (9) `close()` is a no-op.

- [ ] `P3-04` Integration smoke: SubscriptionBackend ABC contract ‖ group:D
  - Creates: (adds to `tests/test_azure_subscription_store.py`)
  - Reads: `agent_sdk/contrib/webhooks/backend.py`
  - Depends: P3-03
  - AC: Parameterized fixture runs the same upsert/get/delete/due_for_renewal contract against both `SubscriptionStore` (tmp_path) and mocked `AzureTableSubscriptionStore`. Both pass identically. Confirms `SubscriptionBackend` ABC substitutability. `GraphSubscriptionManager` constructed with `AzureTableSubscriptionStore` mock and `create()` / `renew()` / `delete()` calls succeed.
