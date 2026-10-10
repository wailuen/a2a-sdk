# w043 — GH-152 sign-in hardening (w042 deferred RT-003 + RT-004)

Two medium findings from `workspace/todos/deferred/w042-group-A2-medium-low.md`, promoted by the
maintainer (2026-10-10, /gh-review) to fix before the 0.9.0 release. Both touch the same files, so
one group, run in order. Bug fixes inside the ratified ADR-003 design — no policy change.
Target: 0.9.0.

---

- [x] `W042-RT003` Two federated sign-ins open in one browser clobber each other's cookie binding ‖ group:G
  - Creates: (modifies `agent_sdk/routes/oauth.py`, `agent_sdk/auth/oidc.py`, `tests/test_gh152_idp_flow_state.py`, `tests/test_gh152_idp_authorize_flow.py`)
  - Reads: `workspace/adr/a003-oauth-idp-sign-in.md` (D4, D9), `workspace/todos/deferred/w042-group-A2-medium-low.md` (RT-003)
  - Severity: medium
  - Root cause: Every federated authorize sets one fixed cookie, `__Host-agent_sdk_idp` (`routes/oauth.py:93`), and `_federate` overwrites it on each call. With two authorize flows open in one browser (two connectors, a retried popup, or Claude.ai re-opening authorize), the later Set-Cookie replaces the earlier binding, so the first flow's callback fails `flows.pop(state, cookie)` and the user lands on the 400 "This sign-in link is invalid or has expired" page. The same applies to the consent step (`flows.pop_consent(ticket, cookie)`).
  - AC: Each in-flight flow has its own browser binding — e.g. a per-flow cookie name `__Host-agent_sdk_idp_<first 16 hex of sha256(state)>`, or one cookie holding a small bounded set of bindings. Callback and consent look up the binding for their own flow. Cookies keep `__Host-` prefix rules (Secure, Path=/, no Domain), HttpOnly, SameSite=Lax, and are cleared when their flow completes or fails.
  - AC: The number of per-flow cookies one browser can accumulate is bounded (stale ones expire with the flow TTL), so the Cookie header can't grow without limit.
  - AC: New test `test_two_concurrent_flows_same_browser_both_complete`: start flow A, then flow B in the same cookie jar, finish B, then finish A — both reach consent and both mint a code. Plus `test_flow_binding_from_other_flow_rejected`: flow A's cookie cannot complete flow B's state.
  - AC: Existing GH-152 tests still pass; single-flow behaviour and the single-use / replay-rejection guarantees are unchanged.
  - SI: SI-2 — no state, nonce, code, ticket or cookie value in logs or error text.
  - GH: https://github.com/wailuen/a2a-sdk/issues/152
  - SI: SI-2  # Supplement to the existing SI-2 line. If the cookie name comes from a hash of the server flow key, the name appears in every Cookie header and in proxy and access logs. Use a truncated hash only, never the raw flow_state or ticket, and never log cookie names or values. Each per-flow cookie must also keep the __Host- rules (Secure, Path=/, no Domain); add a test asserting the Set-Cookie attributes for the new per-flow name.

- [x] `W042-RT004` Anyone can evict real users' in-flight sign-ins by flooding the flow table ‖ group:G
  - Creates: (modifies `agent_sdk/auth/oidc.py`, `agent_sdk/routes/oauth.py`, `tests/test_gh152_idp_flow_state.py`, `docs/security.md`)
  - Reads: `workspace/todos/deferred/w042-group-A2-medium-low.md` (RT-004), `agent_sdk/auth/middleware.py` (`unauth_rate_limit`, client-IP helper)
  - Severity: medium
  - Root cause: DCR is open and GET /oauth/authorize is unauthenticated, so anyone can make `_federate` insert a server-side flow into `IdpFlowStore` (`auth/oidc.py:396`: 1,000-entry LRU, 600 s TTL). At the default unauth limit of 30/min per IP, about 4 source IPs can keep the table full and evict every real user's in-flight flow before they return from Entra, blocking sign-in for the whole tenant.
  - AC: One source cannot evict another source's flows. Pick the simplest sound design and record it in a short note appended to ADR-003 (D4): either a per-client-IP (and/or per-client_id) quota inside `IdpFlowStore`, where a source over quota evicts only its own oldest flow or is refused with a generic `temporarily_unavailable`; or a stateless authorize leg (flow sealed into an AEAD/HMAC-protected `state` bound to the cookie, server keeps only a single-use nonce set). Use the same client-IP source the existing unauth rate limiter uses (respecting its proxy/forwarded-header rules).
  - AC: New test `test_one_ip_cannot_evict_another_ips_flows`: fill the store from IP X past its quota, then confirm a flow started from IP Y before the flood still completes. Plus a test that the overall cap is still enforced.
  - AC: `docs/security.md` "Optional IdP sign-in" section states the per-source limit and what an over-limit caller sees.
  - AC: Existing GH-152 tests still pass.
  - SI: SI-2 — refusal text is generic; no IP, state or client data echoed.
  - GH: https://github.com/wailuen/a2a-sdk/issues/152
  - Reuses: C-023  # Put the per-source quota inside IdpFlowStore (agent_sdk/auth/oidc.py) itself, in the shared _insert() path. Do not add a second limiter in routes/oauth.py. Per LRN-213, the guard must cover every insert into the store: _insert() serves both _flows (put) and _tickets (put_consent). Apply the quota to both tables, or record in the ADR-003 D4 note why tickets are exempt (they are created only after a real IdP sign-in).
  - Reuses: C-024  # C-024 BoundedTtlSingleUseStore (planned, agent_sdk/common/bounded_store.py) was registered so that IdpFlowStore would stop hand-copying the OrderedDict+popitem(last=False) eviction. This todo rewrites that eviction a third time, now with per-source logic. Either build C-024 now with an optional per-key quota and move IdpFlowStore onto it, or update the C-024 registry entry to record that per-source quota is part of the contract the shared store must carry.
  - Reuses: C-023  # Get the client IP from the existing helper: agent_sdk/common/limits.py::client_ip(peer, x-forwarded-for, runtime.trusted_proxies), which middleware._client_key already wraps for unauth_rate_limit. The todo's Reads line points at middleware.py's 'client-IP helper', but _client_key is private. Make it public (or import client_ip directly with AuthRuntime.trusted_proxies). Do not re-parse X-Forwarded-For in oauth.py.
  - SI: SI-5  # The SI: line lists only SI-2, but this todo changes admission on the unauthenticated GET /oauth/authorize auth surface, and the quota key is a security control. (1) Drop the 'and/or per-client_id' option. DCR is open, so anyone can mint unlimited client_ids, and a per-client_id quota does not stop eviction. LRN-210 also says a registration id is not a per-user key. Key the quota on client IP only. (2) The IP must come from client_ip() with trusted_proxies, so X-Forwarded-For counts only when the direct peer is a trusted proxy. Otherwise an attacker can fake a new source on every request and get around the quota. Add an AC and a test: a spoofed X-Forwarded-For from an untrusted peer is billed to the peer's own IP.

---

**Archived 2026-10-10 (by /gh-review).** sdk-wave run wf_93fc4fb0-4ce: unit redteam cleared all
critical/high by round 5 (incl. spoofed X-Forwarded-For billing, IPv6 /64 grouping, fresh-source
refusal instead of evicting others, mypy no-redef); pre-archive gate 2835 passed, 0 failed; mypy clean.
Archive was blocked only by one MCP-audit HIGH outside this wave's scope (non-Entra issuer with no
role/group admits every account at that IdP) — moved to w044 after a maintainer ruling
(https://github.com/wailuen/a2a-sdk/issues/152#issuecomment-6094590732). Medium/low:
`deferred/w043-group-G-medium-low.md`.
