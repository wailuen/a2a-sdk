# Deferred: w000 group A — RESOLVED

- **Wave:** w000
- **Group:** A
- **Date:** 2026-06-14
- **Rounds completed:** 5 (budget exhausted)
- **Resolved:** 2026-07-14
- **Status:** All findings resolved — archive reconciled

---

## Findings (all resolved)

### G-A-001 — medium — RESOLVED
**File:** `agent_sdk/contrib/commitments/store.py`

LSP annotation mismatch: `CommitmentStore.mark_failed` narrowed `reason` to `str` while the ABC `CommitmentBackend.mark_failed` declares `reason: str | None`.

**Fix applied:** `CommitmentStore.mark_failed` now declares `reason: str | None`, matching the ABC contract.

---

### G-A-002 — low — RESOLVED
**File:** `agent_sdk/credentials/crypto.py`

`decrypt()`'s exception handler caught bare `Exception`, silently swallowing `MemoryError`/`RecursionError` and converting them into an opaque `AgentError(INTERNAL, ...)`.

**Fix applied:** Narrowed to `except (InvalidTag, ValueError) as exc:` (imports `cryptography.exceptions.InvalidTag`); `binascii.Error` is a `ValueError` subclass so it remains covered. VM-level exceptions now propagate uncaught. New regression tests in `tests/test_crypto.py` (`test_decrypt_wraps_value_error_as_agent_error`, `test_decrypt_does_not_swallow_memory_error`, `test_decrypt_does_not_swallow_recursion_error`) were written RED first (confirmed failing against the old bare-`Exception` handler) then made GREEN by the fix.

---

### G-A-003 — low — RESOLVED (moot)
**File:** `agent_sdk/contrib/azure_utils.py`

`require_azure_packages()` had zero callers at the time of this finding; it was explicitly deferred ("No immediate code change required") pending the AzureTable backends.

**Resolution:** The AzureTable backends now exist and call it: `agent_sdk/contrib/commitments/azure_table.py`, `agent_sdk/contrib/webhooks/azure_table.py`, and `agent_sdk/credentials/azure_table.py` all invoke `require_azure_packages()` at `__init__`. No further action required.
