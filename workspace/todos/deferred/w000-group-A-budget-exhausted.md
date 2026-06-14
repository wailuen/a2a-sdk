wave: w000
group: A
date: 2026-06-14
round_count: 5
status: budget-exhausted

## Findings

### G-A-001
- severity: medium
- file: /Users/wailuen/Development/a2a-sdk/agent_sdk/contrib/commitments/store.py
- description: LSP annotation mismatch on CommitmentStore.mark_failed. The ABC CommitmentBackend.mark_failed (backend.py line 72) declares `reason: str | None` and its docstring explicitly states 'implementations MUST treat None identically to an empty string'. The concrete CommitmentStore.mark_failed (store.py line 256) narrows the parameter to `reason: str`, violating the Liskov Substitution Principle at the annotation level. A caller holding a CommitmentBackend reference and passing `None` will be flagged as a type error by mypy/pyright even though the runtime implementation handles None correctly via `str(reason or '')`. Any future backend implementation following the ABC signature (accepting None) will diverge from the concrete one.
- fix: Change CommitmentStore.mark_failed signature on line 256 from `reason: str` to `reason: str | None` to match the ABC contract. The existing runtime body `str(reason or '')` already handles None correctly — only the annotation needs updating.
- codify: abc-concrete-mark-failed-annotation-lsp

### G-A-002
- severity: low
- file: /Users/wailuen/Development/a2a-sdk/agent_sdk/credentials/crypto.py
- description: Overly broad and redundant exception handler in decrypt() (line 89): `except (InvalidTag, ValueError, Exception)`. Both InvalidTag and ValueError are subclasses of Exception, so they are dead code in that tuple — the third clause catches them anyway. More importantly, bare `except Exception` also catches MemoryError and RecursionError (both are Exception subclasses), which are catastrophic VM-level conditions that should propagate rather than be swallowed and converted to an AgentError(INTERNAL). The docstring says only `InvalidTag`, `binascii.Error`, and `ValueError` are the intended catches.
- fix: Narrow the exception clause to `except (InvalidTag, ValueError)`. binascii.Error (bad base64 padding) is a subclass of ValueError in Python 3 so it is already covered. This removes the implicit swallowing of MemoryError/RecursionError and eliminates the dead InvalidTag catch. Updated line: `except (InvalidTag, ValueError) as exc:`
- codify: crypto-decrypt-except-too-broad

### G-A-003
- severity: low
- file: /Users/wailuen/Development/a2a-sdk/agent_sdk/contrib/azure_utils.py
- description: require_azure_packages() has zero live callers inside agent_sdk/ as of this wave. The module docstring documents this intentionally ('Until at least one of these ships, require_azure_packages will have no callers') and the function is infrastructure for planned AzureTableTaskStore and AzureTableCommitmentStore backends. Risk: if a contributor implements one of those backends and forgets to call require_azure_packages() at the top of __init__, the optional-dep guard is silently skipped and users get an unclear ImportError instead of the actionable install hint. The gap is low-severity because it is documented, but there is no mechanism to enforce the contract.
- fix: No immediate code change required. When AzureTableTaskStore or AzureTableCommitmentStore are implemented, enforce the call via a base class __init_subclass__ hook or a unit test that instantiates the backend in an environment where the azure packages are mocked as absent and asserts the ImportError message contains 'pip install agent-sdk[azure]'.

## Instruction

Fix remaining findings, then re-run /wave w000.
