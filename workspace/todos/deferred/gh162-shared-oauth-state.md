# GH-162 deferred: shared sign-in storage

Status: deferred (future work). Ruling: https://github.com/wailuen/a2a-sdk/issues/162#issuecomment-6137225080

Current ruling: OAuth/IdP sign-in requires exactly one replica; documented and warned at boot.

Future work: move per-process sign-in state to a shared store.
- IdP flows (`IdpFlowStore`, auth/oidc.py)
- consent tickets and auth codes (auth/oauth_tokens.py)
- access tokens
- MCP sessions (routes/mcp.py)

Design: back the planned C-024 `BoundedTtlSingleUseStore` (`agent_sdk/common/bounded_store.py`, with its C-028 per-source quota option) with a shared store behind the same interface, and move the stores above onto it. Do not build a second per-feature store.

Requirement: single-use items (auth codes, IdP flows, consent tickets) need atomic delete-on-read (ETag or conditional delete) so a code cannot be redeemed twice across replicas. Also close the cross-replica revoke lag.
