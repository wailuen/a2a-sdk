# Component registry

| ID | Name | Location | Status |
|----|------|----------|--------|
| C-001 | crypto | agent_sdk/credentials/crypto.py | present |
| C-002 | CommitmentBackend | agent_sdk/contrib/commitments/backend.py | present |
| C-003 | SubscriptionBackend | agent_sdk/contrib/webhooks/backend.py | present |

## Descriptions

**C-001 crypto** (`agent_sdk/credentials/crypto.py`)
Shared AES-256-GCM encryption module extracted from EncryptedSqliteStore. Exports `derive_key`, `encrypt`, `decrypt`, and `PBKDF2_ITERATIONS`. Reusable by any backend that needs authenticated symmetric encryption with namespace/field AAD binding.

**C-002 CommitmentBackend** (`agent_sdk/contrib/commitments/backend.py`)
Abstract base class extracted from CommitmentStore. Defines the public contract (`add`, `claim_due`, `mark_fired`, `mark_failed`, `cancel`, `reap_stale_firing`, `get`, `list`, `close`) so Azure Table Storage and any future durable-store implementations can be swapped without touching CommitmentExecutor or CommitmentsSource.

**C-003 SubscriptionBackend** (`agent_sdk/contrib/webhooks/backend.py`)
Abstract base class extracted from SubscriptionStore. Defines the public contract (`initialize`, `upsert`, `set_expiration`, `delete`, `get`, `list`, `due_for_renewal`, `close`) so GraphSubscriptionManager and webhooks_renewal_lifespan can accept any backing store (SQLite, Azure Tables, in-memory) via dependency injection.
