wave: w043
group: G
date: 2026-10-10
status: non-blocking (medium/low)

Non-blocking — these did not block w043's archive. Address opportunistically or fold into a future wave.

Findings were accumulated across every unit redteam round for group G and deduped by file+description. Redteam IDs restart each round, so each heading carries its round number (R1–R5). Several findings recur across rounds with different wording. They are kept separately because their descriptions differ, and the theme index below groups them. All are flagged sdkCandidate.

## Theme index

- Per-source flow quota fairness (tie-break evicts oldest, many-IP / IPv6 flood, shared NAT, expired entries counted, full-table refusal DoS, own-flow self-eviction): R1 RT-003, R2 RT-002, R5 RT-006, R5 RT-009
- Consent-ticket table (_tickets) exempt from per-source quota, undocumented: R1 RT-004, R2 RT-004, R3 RT-004, R4 RT-004
- C-024 BoundedTtlSingleUseStore registry entry not updated / third hand-copied eviction: R1 RT-005, R2 RT-005
- ADR-003 / DESIGN.md still describe single `__Host-agent_sdk_idp` cookie; D4 "no refusal path" stale: R1 RT-006, R3 RT-004, R4 RT-005, R5 RT-002
- docs/security.md overclaims ("One caller cannot push other people's sign-ins out", "same derivation"): R2 RT-003, R3 RT-005
- Per-flow cookie not cleared on consent ticket failure; no clear-on-finish tests: R1 RT-007, R2 RT-007, R2 RT-008, R3 RT-006, R4 RT-003, R5 RT-001
- Cookie Max-Age (600 s from authorize) not refreshed at callback vs 300 s consent TTL: R2 RT-009, R4 RT-002, R5 RT-008
- Private `_client_key` imported across modules; `_source_key` duplicates folding: R1 RT-008, R2 RT-010, R3 RT-007, R4 RT-006, R5 RT-005
- `_client_key` /64 folding changes every SDK rate limiter, undocumented: R5 RT-004
- Spoofed X-Forwarded-For integration test missing / weak: R2 RT-006, R4 RT-007
- Route-level full-table refusal (temporarily_unavailable) untested: R4 RT-003, R5 RT-007
- `IdpFlowStore.put` source defaults to "" (fairness opt-in): R3 RT-008
- `_split_ticket` does not require hex flow_id: R3 RT-010
- CHANGELOG [Unreleased] missing w043 runtime changes: R3 RT-010, R5 RT-003
- Test hygiene (ruff issues, legacy cookie name in unknown-state tests, duplicated helpers, FlowCookie spacing): R1 RT-009, R3 RT-009, R4 RT-007

## Findings

### R1 RT-003 — medium — agent_sdk/auth/oidc.py
When the table is full, _evict_for (lines 435-448) evicts from `max(counts, key=counts.get)`. On a tie, that picks the first source seen, which is the oldest flow's source. A flood of many distinct sources with 1 flow each therefore evicts a real user's flow that started before the flood. Verified: with max_entries=20, the victim at 2001:db8::1 followed by 40 single-flow IPv6 sources means victim pop returns None. A single IPv6 host owns 2^64 addresses (keys are full addresses, not /64), and RT-001 gives the same result over IPv4. So the AC 'One source cannot evict another source's flows' only holds for the few-IP case the tests cover. docs/security.md:47 says 'One caller cannot push other people's sign-ins out', which is wrong in these cases. The ADR-003 D4 residual note says the per-IP rate limit bounds this, but a per-IP limit does not bound many IPs.
- Fix: When the table is full and no existing source holds strictly more flows than the incoming source would after insert, refuse the new flow (return None, and have _federate send temporarily_unavailable) instead of evicting another source's oldest flow. Collapse IPv6 sources to their /64 for the quota key. Add a test: a victim flow followed by >max_entries distinct single-flow sources still completes. Correct docs/security.md:47 and the ADR-003 D4 residual note.
- Codify: A 'largest source loses' eviction needs a tie-break that never hits the oldest small source, and IPv6 quota keys must be prefix-aggregated, or per-source fairness falls apart under a many-address flood.

### R1 RT-004 — medium — agent_sdk/auth/oidc.py
The todos-redteam annotation (C-023/LRN-213) required the per-source quota to sit in the shared _insert() path covering both _flows and _tickets, or an ADR-003 D4 note explaining why tickets are exempt. The quota lives only in put() via _evict_for (line 459). put_consent (line 476) still uses plain global LRU popitem in _insert (lines 419-424). The ADR-003 D4 note (workspace/adr/a003-oauth-idp-sign-in.md:111) does not mention tickets. Any tenant user who signs in repeatedly can evict other users' pending consent tickets.
- Fix: Either carry `source` into put_consent and apply the same per-source eviction in _insert for both tables, or append a sentence to the ADR-003 D4 note saying tickets are exempt and why (each needs a full IdP sign-in plus tenant assignment, bounded by the unauth rate limit), and add a test that pins whichever behaviour is chosen.
- Codify: When an eviction guard is added to a store with two tables, apply it at the shared insert or write down the exemption; a guard on one call site is the LRN-213 pattern again.

### R1 RT-005 — medium — workspace/components/README.md
The W042-RT004 annotation (C-024) required either building BoundedTtlSingleUseStore with an optional per-key quota and moving IdpFlowStore onto it, or updating the C-024 registry entry to record per-source quota as part of the shared store's contract. Neither happened. Line 27 and lines 153-154 still list C-024 as planned with no quota mention. IdpFlowStore now hand-copies the OrderedDict+popitem eviction a third time and adds a separate O(n) per-source scan (oidc.py:435-448).
- Fix: Update the C-024 entry so per-source quota, largest-source tie-break and refusal semantics are part of the planned contract, and list IdpFlowStore._evict_for as a copy to migrate. Or implement agent_sdk/common/bounded_store.py now and rebase IdpFlowStore on it.

### R1 RT-006 — medium — workspace/adr/a003-oauth-idp-sign-in.md
The spec still describes one fixed browser-binding cookie. ADR-003 line 107 says 'Browser-binding cookie: `__Host-agent_sdk_idp`', and the DESIGN.md:399 IdP addendum says 'sets the `__Host-agent_sdk_idp` browser-binding cookie'. The code now sets a per-flow `__Host-agent_sdk_idp_<16 hex of sha256(state)>` cookie (routes/oauth.py:99-109), keeps at most 8 (line 101), and binds consent tickets as `<flow_id>.<ticket>` (line 823). No ADR D9 note records the W042-RT003 design, the cookie cap, or the fact that the hashed name appears in Cookie headers and proxy logs.
- Fix: Add a D9 note to ADR-003 (per-flow cookie name derivation, 8-cookie cap with oldest cleared first, the flow_id.ticket consent form value, and a truncated-hash-only rule for names) and update DESIGN.md:399 to match.

### R1 RT-007 — medium — tests/test_gh152_idp_authorize_flow.py
The W042-RT003 AC says per-flow cookies are 'cleared when their flow completes or fails'. No test asserts a Max-Age=0 Set-Cookie on consent allow or deny, on callback deny or outage, or on replay. test_flow_cookies_bounded_and_cleared (line 672) only checks len(jar) <= 8. The consent route also fails to clear on one failure path: when pop_consent returns None (routes/oauth.py:836-837), it returns _idp_local_error() without clearing the flow's cookie, unlike the matching callback branch at line 801.
- Fix: In oauth_idp_consent, clear the named cookie when flow_id is valid and a cookie was presented, even if the ticket lookup fails. Add tests asserting a deletion Set-Cookie for the flow's own name after (a) consent allow, (b) consent deny, (c) callback IdpDenied, (d) callback with an unknown state but a presented cookie, (e) consent with an expired ticket. Also assert that the newest flow still completes after the 8-cookie trim.

### R1 RT-008 — low — agent_sdk/routes/oauth.py
routes/oauth.py imports the private middleware helper `_client_key` (line 56) to key the flow quota. The todos-redteam annotation said to make it public or import common.limits.client_ip with AuthRuntime.trusted_proxies, not to reach across modules for a private name. The ADR-003 D4 note also cites `_client_key` by its private name.
- Fix: Rename it to a public `client_key(request, runtime)` in auth/middleware.py, re-export it, and update the three middleware call sites, routes/oauth.py:716 and the ADR note.

### R1 RT-009 — low — tests/test_gh152_idp_authorize_flow.py
ruff (project config) reports 18 issues in the scoped files. In the tests: unused unpacked variables (RUF059 at lines 277, 467, 478, 487, 625, 655, 656, 682, e.g. `verifier` in _begin_with and `qa`/`cb_` in the concurrent-flow test) and nested `with` blocks (SIM117). In agent_sdk/auth/oidc.py: SIM117 at line 136 and blind `except Exception` (BLE001) at lines 153 and 208. In routes/oauth.py: F811 (see RT-002) and SIM102 at line 358.
- Fix: Prefix unused unpacked names with an underscore, merge nested with-blocks, and either narrow the oidc.py catches (httpx.HTTPError, ValueError, jwt.PyJWKSetError) or add `# noqa: BLE001` with a one-line SI-2 reason.

### R2 RT-002 — medium — agent_sdk/auth/oidc.py
[SDK] The per-source quota (_MAX_FLOWS_PER_SOURCE=50, oidc.py:42) is keyed on client IP. The main deployment for this feature is an Entra tenant, where staff sign in from behind one corporate NAT or egress IP. If more than 50 people at one site start sign-in within the 600 s flow lifetime, they evict each other's flows. When the global table is full, that site is also 'the source holding the most flows' and loses its flows first. Expired flows are never removed before counting (_evict_for counts every entry), so stale entries also count against the quota.
- Fix: Remove expired entries in _evict_for before counting. Make the per-source quota configurable (a setting next to the rate-limit settings), and state the shared-NAT effect in docs/security.md and the ADR-003 D4 note. Consider evicting only expired or over-fair-share entries before evicting live ones from a large source.

### R2 RT-003 — medium — docs/security.md
[SDK] docs/security.md:47 says 'One caller cannot push other people's sign-ins out', with no caveat. The ADR-003 D4 note (workspace/adr/a003-oauth-idp-sign-in.md:111) admits a residual risk from attackers with many IPs, but says 'the per-IP rate limit is the bound there'. That is false for IPv6 (see RT-001). Neither document mentions the tie-break that evicts the oldest source. Operators get a security guarantee that the code does not provide.
- Fix: After fixing RT-001, write down the real guarantee and its remaining risk in both places: many sources or a large IPv6 prefix can still fill the table, and the exact result is either refusal or eviction. Remove the absolute sentence 'One caller cannot push other people's sign-ins out' unless the code enforces it.

### R2 RT-004 — medium — agent_sdk/auth/oidc.py
[SDK] The planning annotation on W042-RT004 (Reuses: C-023, LRN-213) required one of two things: apply the per-source quota to both tables in the shared _insert() path, or record in the ADR-003 D4 note why consent tickets are exempt. The quota is applied only in put() through _evict_for (oidc.py:459). put_consent (oidc.py:476-482) still uses plain global LRU eviction over 1,000 entries. The ADR D4 note does not mention tickets at all. A tenant member who scripts repeated sign-ins can evict other users' pending consent tickets.
- Fix: Either pass source through put_consent and apply the same per-source logic to _tickets (the callback has the request, so it can compute the source), or add one sentence to the ADR-003 D4 note explaining why tickets are exempt (each needs a real IdP sign-in) and what the remaining risk is.

### R2 RT-005 — medium — workspace/components/README.md
The C-024 annotation on W042-RT004 required one of two things: build BoundedTtlSingleUseStore with a per-key quota and move IdpFlowStore onto it, or update the C-024 registry entry to state that per-source quota is part of its contract. Neither was done. agent_sdk/common/bounded_store.py does not exist, and the C-024 entry (README.md:153-154) is unchanged. _evict_for adds a third hand-written eviction scheme in IdpFlowStore.
- Fix: Update the C-024 entry to add an optional per-key quota with fair eviction to the contract the shared store must provide, and cite IdpFlowStore._evict_for as the reference behaviour. Or build C-024 now and move IdpFlowStore onto it.

### R2 RT-006 — medium — tests/test_gh152_idp_authorize_flow.py
[SDK] The SI-5 annotation on W042-RT004 asked for an AC and a test showing that a spoofed X-Forwarded-For from an untrusted peer is billed to the peer's own IP for the flow quota. No such test exists. tests/test_client_ip_xff.py only unit-tests client_ip(). No test drives GET /oauth/authorize with a forged X-Forwarded-For and checks the source recorded on the stored FlowState. Nothing pins the link from routes/oauth.py:715 to IdpFlowStore.
- Fix: Add an integration test: with trusted_proxies empty, send several authorize requests with different X-Forwarded-For values. Assert that every FlowState.source in app.state.idp_flows._flows equals the test-client peer, and that the quota evicts across those requests as one source. Add a trusted-proxy case that uses the rightmost untrusted hop.

### R2 RT-007 — low — tests/test_gh152_idp_authorize_flow.py
In test_flow_binding_from_other_flow_rejected, the second assertion proves nothing. The first request already burns flow B, because _take pops before it checks the binding. The second request then fails because B is gone, not because the cookie is rejected. test_flow_cookies_bounded_and_cleared does not check 'cleared': no test asserts that a completed or failed flow sends a Max-Age=0 Set-Cookie for its own __Host-agent_sdk_idp_<id> name with Secure and Path=/.
- Fix: Use a fresh flow B for each negative case, or assert that B can still be completed with its own cookie when the mismatch is checked without consuming the flow. Add assertions that the consent-allow, deny and callback-error responses each delete the matching per-flow cookie with __Host- attributes.

### R2 RT-008 — low — agent_sdk/routes/oauth.py
When the consent ticket lookup fails, oauth_idp_consent (oauth.py:834-836) returns _idp_local_error() without clearing the per-flow cookie. The callback route clears it in the same case. The W042-RT003 AC says cookies 'are cleared when their flow completes or fails'.
- Fix: When flow_id is non-empty and the cookie is present, return _clear_flow_cookie(_idp_local_error(), name), matching the callback route.

### R2 RT-009 — low — agent_sdk/routes/oauth.py
The per-flow cookie is set once at authorize with Max-Age=600 (oauth.py:99,115) and is not refreshed at the callback. The consent ticket lives 300 s from the callback. A user who spends more than 5 minutes at the IdP (MFA, password reset) gets a consent window of only 600 minus elapsed seconds. The browser then drops the cookie and Allow fails with 'link invalid or expired'.
- Fix: In oauth_idp_callback, re-set the same cookie with max_age equal to the consent TTL when showing the consent page, or set the authorize Max-Age to flow TTL plus consent TTL.

### R2 RT-010 — low — agent_sdk/routes/oauth.py
routes/oauth.py:56 imports the private helper _client_key from auth.middleware. The todo-plan annotation (Reuses: C-023) said to make it public or import common.limits.client_ip directly. A cross-module dependency on a private name is fragile: a rename in middleware silently breaks the quota source.
- Fix: Rename _client_key to client_key, keeping the old name as an alias for internal callers, or call client_ip(request.client.host, request.headers.get('x-forwarded-for'), runtime.trusted_proxies) directly in _federate.

### R3 RT-004 — medium — workspace/adr/a003-oauth-idp-sign-in.md
[SDK] ADR-003 D4 no longer matches the code. (1) The D4 note (line 111) says 'No refusal path, so nothing to echo', but IdpFlowStore._evict_for raises IdpUnavailable when the table is full and the heaviest source is not above own+1, and `_federate` turns that into a temporarily_unavailable redirect (confirmed by probe). (2) Line 107 still names the single cookie `__Host-agent_sdk_idp`. The landed design is a per-flow `__Host-agent_sdk_idp_<16 hex of sha256(state)>` plus an 8-cookie bound, and D4 records neither. (3) The C-023/LRN-213 annotation required the D4 note to record why the consent-ticket table (_tickets, plain global LRU in _insert) is exempt from the per-source quota. It does not.
- Fix: Update D4: describe the per-flow cookie name, the 8-cookie cap and the clear-on-finish rule. Replace 'No refusal path' with the actual refusal condition and its generic temporarily_unavailable outcome. Add one sentence explaining why tickets are exempt (created only after a real IdP sign-in, TTL 5 min), or apply the quota to tickets.

### R3 RT-005 — medium — docs/security.md
[SDK] The new per-source paragraph overclaims. It says 'One caller cannot push other people's sign-ins out', but a fresh source does evict the heaviest other source's oldest flow when the table is full (see RT-001). It never mentions that a legitimate new user can be refused with temporarily_unavailable when the table is full of equal-weight sources. It says the source is 'same derivation as the unauthenticated rate limit', but the flow store groups IPv6 by /64 and folds IPv4-mapped addresses into IPv4, while the rate limiter keys on the raw address string.
- Fix: Rewrite the bullet to state the real behavior: per-IP (IPv6 /64) quota of 50; when the 1,000-entry table is full, either the heaviest source loses its oldest or the newcomer gets temporarily_unavailable. Drop the absolute 'cannot push out' claim, or fix the code (RT-001) so it becomes true. Correct the derivation sentence.

### R3 RT-006 — medium — agent_sdk/routes/oauth.py
[SDK] The W042-RT003 AC requires per-flow cookies to be 'cleared when their flow completes or fails'. In oauth_idp_consent, the found-is-None branch (line 838: expired, replayed or mismatched ticket) returns _idp_local_error() without clearing the flow cookie, so a failed consent leaves the cookie until Max-Age 600. No test asserts cookie clearing on any path (success consent, deny, callback failure). test_flow_cookies_bounded_and_cleared only checks the 8-cookie bound despite its name.
- Fix: In oauth_idp_consent, clear `name` on the found-is-None branch whenever flow_id is well-formed and the cookie is present. Add tests asserting a Max-Age=0 Set-Cookie for the per-flow name, with Secure and Path=/ kept, after consent allow, consent deny, callback failure and consent-ticket failure.

### R3 RT-007 — low — agent_sdk/routes/oauth.py
[SDK] routes/oauth.py imports the private `_client_key` from auth/middleware (line 56, used at 716). The todo's Reuses annotation explicitly said to make it public or call client_ip(peer, xff, runtime.trusted_proxies) directly. A cross-module dependency on a private name can be renamed or changed without notice.
- Fix: Rename `_client_key` to a public `client_key` (keep a private alias for internal callers), or call common.limits.client_ip with runtime.trusted_proxies in `_federate`.

### R3 RT-008 — low — agent_sdk/auth/oidc.py
[SDK] IdpFlowStore.put's `source: str = ""` default (line 476) means any caller that leaves out source silently puts all flows into one bucket. That disables per-source fairness without any error. The public signature makes the security control opt-in.
- Fix: Make `source` a required keyword-only argument (no default), or reject an empty source, and update the unit-test helper `_put` to pass a source explicitly.

### R3 RT-009 — low — tests/test_gh152_idp_authorize_flow.py
[SDK] Test hygiene issues. (1) test_callback_unknown_state_rejected (line 265) and test_consent_unknown_ticket_rejected (line 498) still send the old single-cookie name `__Host-agent_sdk_idp=x`. The route now never looks that cookie up, so neither test exercises the binding check. (2) `class FlowCookie(str)` (line 39) runs straight into the module-level KEY with no blank lines. (3) cookie_value and cookie_value_of duplicate the same parsing. (4) _begin_with returns an unused `None` first tuple element.
- Fix: Use per-flow cookie names in the two unknown-state/ticket tests, so they reach flows.pop and pop_consent with a present but unbound cookie. Merge cookie_value/cookie_value_of, drop the dead tuple element, and fix the FlowCookie formatting.

### R3 RT-010 — low — agent_sdk/routes/oauth.py
[SDK] Two small gaps. (1) _split_ticket (line 128) checks only that the flow_id is 16 characters long, not that it is hex, so attacker-chosen characters from the form go into the cookie-name lookup and, on later branches, into delete_cookie. (2) CHANGELOG [Unreleased] does not mention the w043 runtime changes: the per-flow cookie name pattern (which operators may key proxy or WAF rules on) and the new per-source flow quota with its temporarily_unavailable refusal.
- Fix: Require `re.fullmatch(r"[0-9a-f]{16}", flow_id)` in _split_ticket. Add a GH-152 w043 bullet under CHANGELOG [Unreleased] describing per-flow `__Host-agent_sdk_idp_<id>` cookies (max 8 per browser) and the 50-per-IP flow quota and its refusal behavior.

### R4 RT-002 — medium — agent_sdk/routes/oauth.py
[SDK] The cookie lifetime and the consent-ticket lifetime do not line up, so a valid sign-in can fail at the Allow step. _federate sets the per-flow cookie with Max-Age=600 (_IDP_COOKIE_MAX_AGE), counted from authorize. oauth_idp_callback creates a consent ticket that lives 300 s (_CONSENT_TTL) from the callback, but it never refreshes the cookie. Example: a user returns from Entra at t=500 s and clicks Allow at t=650 s. The ticket is still valid, but the browser has already dropped the cookie. oauth_idp_consent finds no cookie, and the user lands on the 400 'This sign-in link is invalid or has expired' page. The value 600 is also hard-coded apart from oidc._FLOW_TTL, so the two can drift.
- Fix: In oauth_idp_callback, re-set the same per-flow cookie with Max-Age equal to the consent TTL on the consent-page response. Derive both Max-Age values from the IdpFlowStore TTLs (expose flow_ttl/consent_ttl) instead of the separate 600 constant. Add a test with a patched _now: callback at t=500, consent at t=650 succeeds, and the consent-page response carries a refreshed Set-Cookie.

### R4 RT-003 — medium — tests/test_gh152_idp_authorize_flow.py
[SDK] Two W042-RT003/RT004 requirements have no test. (1) The AC says per-flow cookies 'are cleared when their flow completes or fails', but no test checks for a Max-Age=0 or empty Set-Cookie on the consent success redirect, consent deny, or callback failure (cookie mismatch, IdP error, IdpDenied). test_flow_cookies_bounded_and_cleared, despite its name, only checks the cap of 8. (2) The route-level refusal when the table is full is never tested: no test proves /oauth/authorize turns IdpUnavailable from flows.put into a temporarily_unavailable redirect that carries the client state and no Set-Cookie. Also, test_callback_unknown_state_rejected and test_consent_unknown_ticket_rejected still send the old fixed cookie name '__Host-agent_sdk_idp=x'. The server no longer reads that name, so these tests no longer exercise a cookie-present path.
- Fix: Add tests that assert a clearing Set-Cookie for the flow's own cookie name on: consent allow (303), consent deny, callback cookie mismatch, and callback IdpDenied. Add a route test with IdpFlowStore(max_entries=1, per_source_max=1), filled from another peer, that asserts the error=temporarily_unavailable redirect and no set-cookie. Update the two legacy tests to use a per-flow cookie name (cookie_name(state)).

### R4 RT-004 — medium — workspace/adr/a003-oauth-idp-sign-in.md
[SDK] The todo's C-023/LRN-213 note required one of two things: apply the per-source quota to both tables that IdpFlowStore._insert serves (_flows and _tickets), or record in the ADR-003 D4 note why consent tickets are exempt. put_consent (agent_sdk/auth/oidc.py:495-501) still uses plain global LRU eviction. The D4 note says nothing about tickets. Any directory user who can script silent IdP sign-ins can create up to 1,000 tickets and evict other users' pending consent tickets. The exemption is undocumented and unjustified.
- Fix: Either pass source= into put_consent and run the same _evict_for logic over _tickets, or add a sentence to the ADR-003 D4 note. That sentence should say tickets are exempt because each one needs a successful upstream IdP sign-in plus code exchange by a directory user, and name the residual risk.

### R4 RT-005 — medium — workspace/adr/a003-oauth-idp-sign-in.md
[SDK] The ADR-003 D4 body (lines 107-109) still says the browser-binding cookie is the single fixed '__Host-agent_sdk_idp' with Max-Age=600. W042-RT003 replaced it with per-flow cookies named '__Host-agent_sdk_idp_<first 16 hex of sha256(state)>' (agent_sdk/routes/oauth.py:_flow_cookie_name), capped at 8 per browser (_IDP_MAX_FLOW_COOKIES), with the flow id carried as a prefix in the consent ticket ('<flow_id>.<ticket>', _split_ticket). The accepted ADR no longer matches the wire behaviour. Anyone following the ADR, such as a reverse-proxy rule or a cookie allow-list, would target a cookie that no longer exists.
- Fix: Add a D4 note (GH-152 RT-003) covering: the per-flow cookie name derivation (truncated hash only, never the raw state), the cap of 8 with oldest-first clearing, the '<flow_id>.<ticket>' consent form value, and clearing on completion or failure.

### R4 RT-006 — medium — agent_sdk/auth/oidc.py
[SDK] The client-IP key logic now exists twice, and a private helper is used across modules. IdpFlowStore._source_key (oidc.py:435-445) copies the IPv4-mapped and IPv6 /64 normalisation from agent_sdk/auth/middleware.py:_client_key line for line. routes/oauth.py imports the private _client_key from middleware. The todo's C-023 note said to make _client_key public, or to import limits.client_ip with trusted_proxies. If the rate limiter's bucketing changes (say /56), the flow quota silently keys sources differently from the rate limiter. The docs promise the two use the 'same derivation'.
- Fix: Rename middleware._client_key to a public client_key (keep a private alias if needed) and import that in routes/oauth.py. Delete _source_key from IdpFlowStore and treat source as an already-normalised opaque key, or have both call one shared normaliser in agent_sdk/common/limits.py.

### R4 RT-007 — low — tests/test_gh152_idp_authorize_flow.py
[SDK] Test file hygiene. The FlowCookie class (lines 39-41) runs straight into the module constant KEY with no blank lines. cookie_value() reads r.headers['set-cookie'], which httpx joins when there are several Set-Cookie headers. _federate emits stale-cookie deletions before the new cookie, so any test whose request carries 8+ prior flow cookies would match a deletion header. Only cookie_value_of() handles that case. The assertion `r.status_code != 200 or "ticket" not in r.text` in test_spoofed_xff_from_untrusted_peer_billed_to_peer is weak: it passes on any non-200, including a 500.
- Fix: Add PEP 8 spacing around FlowCookie. Replace cookie_value() with cookie_value_of() (iterate get_list and skip deletions). In the spoofed-XFF test, assert r.status_code == 400 and that 'location' is not in r.headers for the evicted first flow.

### R5 RT-001 — medium — agent_sdk/routes/oauth.py
W042-RT003 AC says each per-flow cookie is cleared when its flow completes or fails. oidc_idp_consent's `found is None` branch (oauth.py:838-839) returns _idp_local_error() without clearing the per-flow cookie, even when the cookie exists (replayed, mismatched or expired ticket). No test checks that a cookie is cleared on completion or failure. test_flow_cookies_bounded_and_cleared only checks the 8-cookie bound, despite its name.
- Fix: In oauth_idp_consent, when flow_id is well-formed and the cookie is present, return `_clear_flow_cookie(_idp_local_error(), name)` (same pattern as the callback at line 803). Add tests that assert a Max-Age=0 Set-Cookie for the per-flow name on: consent success (303), consent deny, consent with an unknown or replayed ticket, and callback failure. Rename or split test_flow_cookies_bounded_and_cleared.
- Codify: An AC with the words 'cleared on complete or fail' needs one test per exit branch. A bound test named '..._cleared' does not prove cleanup.

### R5 RT-002 — medium — workspace/adr/a003-oauth-idp-sign-in.md
ADR-003 D4 (line 107) and the DESIGN.md §5.5 IdP addendum (line 399) still describe one fixed `__Host-agent_sdk_idp` browser-binding cookie. The code now sets a per-flow `__Host-agent_sdk_idp_<16-hex sha256(state)>` cookie (oauth.py:98-132), caps it at 8 per browser, and uses a `<flow_id>.<ticket>` consent-ticket format. None of these RT-003 design changes appear in the ADR or DESIGN.md. Only the RT-004 quota got a D4 note.
- Fix: Add a 'D4 note (GH-152 RT-003) — per-flow cookie' to ADR-003. Cover: the name derivation (a truncated hash of the server state, never the raw value), the 8-cookie bound with oldest-first clearing, and the `<flow_id>.<ticket>` form field. Update the DESIGN.md:399 addendum and the ADR line 107 cookie sentence to match.

### R5 RT-003 — medium — CHANGELOG.md
CHANGELOG [Unreleased] has no entry for the w043 runtime changes. Missing: the per-source in-flight sign-in quota (50 per IP or IPv6 /64), the new full-table refusal (`error=temporarily_unavailable`), the per-flow cookie name change and the new consent-ticket format. The wave updated docs/security.md and the ADR to match the new code but not CHANGELOG.md, which is the LRN-199 / LRN-267 tell.
- Fix: Under [Unreleased], extend the GH-152-B/C bullet (or add a 'GH-152 sign-in hardening (w043)' bullet). Describe the per-source quota and its refusal behaviour, the per-flow `__Host-agent_sdk_idp_<id>` cookies (operators with cookie allow-lists or WAF rules need the new name pattern), and the IPv6 /64 grouping of client keys.

### R5 RT-004 — medium — agent_sdk/auth/middleware.py
`_client_key` (middleware.py:55-66) now folds IPv6 addresses into their /64 and IPv4-mapped addresses into IPv4. This changes the key for every unauthenticated rate limiter and every identity-fallback limiter in the SDK (A2A, AG-UI and /mcp 401 paths, /oauth/register, /oauth/authorize), not only the IdP flow quota. The change sits outside both todos' declared Creates/Modifies scope (LRN-202). docs/security.md 'Rate limiting and proxies' does not mention it. Only the IdP bullet says 'an IPv6 address counts as its /64'. There is no CHANGELOG entry.
- Fix: Either record the SDK-wide /64 rate-limit keying in docs/security.md 'Rate limiting and proxies' and in CHANGELOG [Unreleased], with a test pinning the unauth limiter behaviour for two addresses in one /64, or scope the /64 folding to the IdP flow-quota key only and leave the shared limiter key unchanged.

### R5 RT-005 — medium — agent_sdk/auth/oidc.py
Component-reuse drift. routes/oauth.py:56 imports the private `middleware._client_key` across modules, but the todo annotation (C-023) required making it public or calling `common.limits.client_ip` with `trusted_proxies`. Separately, `IdpFlowStore._source_key` (oidc.py:435-445) copies the IPv4-mapped and IPv6 /64 folding that `_client_key` already does. On the real route path `_source_key` gets an already-folded '2001:db8::/64' string, fails `ip_address()`, and returns it unchanged. So the store copy is dead in production and only exercised by direct unit tests, and the two copies can silently drift (for example if one moves to /56).
- Fix: Expose a public `client_key(request, runtime)` (or `normalize_client_key(ip)` in common/limits.py) and import that in oauth.py. Delete `IdpFlowStore._source_key`, or make it call the shared normalizer, so there is one folding rule. Point the ADR-003 D4 note at the public symbol.

### R5 RT-006 — medium — agent_sdk/auth/oidc.py
Leftover tenant-wide sign-in denial of service is larger than documented. `_evict_for` (oidc.py:447-466) refuses every source holding no flows once the 1,000-entry table is full. Each source may hold 50 flows, and IPv6 is grouped only by /64. So a single residential IPv6 /56 (256 /64s), or 20 IPv4 addresses, can fill the table. About 5 requests per minute per source keeps it full, far below the 30/min unauth limit, so the refusal lasts as long as the attack, not just 10 minutes. Every new real user then gets `temporarily_unavailable`. docs/security.md and ADR D4 describe this as 'about 20 IPs', which hides that one IPv6 customer can do it.
- Fix: Group IPv6 more coarsely for the flow quota (/56 or /48), or add a second-tier quota per larger prefix. Alternatively keep headroom: set the per-source cap so (cap × the expected number of attacker prefixes) cannot fill the table, or reserve a slice of the table that only sources with zero flows may use. At minimum, update docs/security.md and the ADR residual-risk text to say that one IPv6 /56 is enough and that the refusal lasts as long as the flood continues.

### R5 RT-007 — low — tests/test_gh152_idp_authorize_flow.py
No route-level test covers the new full-table refusal path in `_federate` (oauth.py:718-719, where `flows.put` raises IdpUnavailable and the route returns a temporarily_unavailable redirect). The store-level tests prove the raise. Nothing proves that the HTTP caller gets a 302 to the registered redirect_uri with `error=temporarily_unavailable`, only its own `state`, and no Set-Cookie, which is what the RT-004 AC and docs/security.md promise.
- Fix: Add a route test. Install `IdpFlowStore(max_entries=1, per_source_max=1)`, fill the table from peer A, authorize from peer B, then assert status 302, error=temporarily_unavailable, state equals the client state, and no set-cookie header.

### R5 RT-008 — low — agent_sdk/routes/oauth.py
The per-flow cookie gets Max-Age=600 at authorize and is never refreshed at callback. The consent ticket gets a fresh 300 s lifetime at callback (oidc.py:40, oauth.py:824). If the user spends more than about 5 minutes at the IdP (MFA enrolment, password reset), the cookie expires before the ticket does. Clicking Allow then shows 'This sign-in link is invalid or has expired' even though the ticket is still valid.
- Fix: In oauth_idp_callback's success path, re-set the same per-flow cookie with max_age matching the consent TTL (or keep the cookie Max-Age at least flow TTL plus consent TTL). Add a time-travel test: callback at t=500 s, consent at t=650 s, and the flow succeeds.

### R5 RT-009 — low — agent_sdk/auth/oidc.py
When the table is full, a source that already holds flows evicts its own oldest flow (oidc.py:457-460). Under attack, a real user with one sign-in open who opens a second one (a retried popup, or two connectors) loses the first. That is exactly the RT-003 two-concurrent-flows case, so the RT-003 guarantee breaks silently under load. Also, the quota is keyed per IP, so all employees behind one corporate NAT or egress IP share one 50-flow quota. One insider or compromised host on that NAT can still push out colleagues' in-flight sign-ins. Neither limit is documented.
- Fix: Document both limits in the docs/security.md IdP bullet and the ADR D4 note: same-IP sources share one quota, and concurrent flows can be lost when the table is full. Optionally, when the table is full, refuse a source that already holds flows instead of evicting, if it is under a small floor (for example fewer than 2 flows).
