# Component registry

| ID | Name | Location | Status |
|----|------|----------|--------|
| C-001 | crypto | agent_sdk/credentials/crypto.py | present |
| C-002 | CommitmentBackend | agent_sdk/contrib/commitments/backend.py | present |
| C-003 | SubscriptionBackend | agent_sdk/contrib/webhooks/backend.py | present |
| C-004 | uv-lockfile-bootstrap convention | harness/reference/uv-lockfile-bootstrap.md (new) | planned |

## Descriptions

**C-001 crypto** (`agent_sdk/credentials/crypto.py`)
Shared AES-256-GCM encryption module extracted from EncryptedSqliteStore. Exports `derive_key`, `encrypt`, `decrypt`, and `PBKDF2_ITERATIONS`. Reusable by any backend that needs authenticated symmetric encryption with namespace/field AAD binding.

**C-002 CommitmentBackend** (`agent_sdk/contrib/commitments/backend.py`)
Abstract base class extracted from CommitmentStore. Defines the public contract (`add`, `claim_due`, `mark_fired`, `mark_failed`, `cancel`, `reap_stale_firing`, `get`, `list`, `close`) so Azure Table Storage and any future durable-store implementations can be swapped without touching CommitmentExecutor or CommitmentsSource.

**C-003 SubscriptionBackend** (`agent_sdk/contrib/webhooks/backend.py`)
Abstract base class extracted from SubscriptionStore. Defines the public contract (`initialize`, `upsert`, `set_expiration`, `delete`, `get`, `list`, `due_for_renewal`, `close`) so GraphSubscriptionManager and webhooks_renewal_lifespan can accept any backing store (SQLite, Azure Tables, in-memory) via dependency injection.

**C-004 uv-lockfile-bootstrap convention** (`harness/reference/uv-lockfile-bootstrap.md (new)`)
GH-70b (setup), GH-70c (new-agent) and GH-70d (template/Dockerfile) all independently implement the same three-step convention: run `uv lock` to generate an initial uv.lock after template render, install with `uv sync --frozen` (no bare pip / no editable install), and `git add uv.lock` in the scaffold/upgrade commit. GH-70a (upgrade) re-locks the same way. This is one reusable harness convention being copied into four places, so the exact command sequence and rollback notes will drift between skills over time. Extract a single reference doc (or a shared command snippet) that all four todos point at, so the lock+frozen-install+commit recipe is defined once. Also: the template/ scaffold currently ships pyproject.toml with NO uv.lock (confirmed: template/uv.lock absent), so GH-70d's `COPY uv.lock ./` will fail at docker build unless GH-70b/GH-70c actually generate and commit template/uv.lock first — the four todos share an implicit ordering/artifact dependency on the committed lockfile that the group:G 'all independent' framing hides.
