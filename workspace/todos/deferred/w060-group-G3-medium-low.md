# w060 — deferred medium/low findings (unit:G3)

- Wave: w060
- Scope: unit:G3
- Date: 2026-10-23

Non-blocking — these did not block w060's archive. Address opportunistically or fold into a future wave.

## RT-002 (medium) — agent_sdk/routes/oauth.py:1049 [sdkCandidate]

Quote: `method = store.client_auth_method(client_id) if client_id else None`

[SDK] _authenticate_client fails open when the client record is missing: a None method skips the secret check, and consume_code / rotate_refresh still succeed because they only compare the client_id string. Example: a user-consented confidential client has no refresh family yet, so it can be evicted between consent and code exchange; it can then redeem the code, and every later refresh, with no secret. client_auth_method also downgrades a record with a non-string method to 'none'. This breaks the AC that refresh checks 'the client record bound to the refresh family', and breaks fail-closed design.

Fix: On the token and refresh grants, return 401 invalid_client when client_auth_method(client_id) is None (unknown or evicted client), instead of passing through to the grant lookup. In client_auth_method, treat a record with a missing or unknown method, or with a client_secret_hash present, as confidential/invalid, never as 'none'. Add a test: evict a confidential client after mint_code, then show that both the code exchange and the refresh are rejected.

Codify: Client authentication must fail closed: when the stored client record is missing or malformed, reject the request; never skip the secret check and leave the decision to a later id-string compare.

## RT-003 (medium) — agent_sdk/routes/oauth.py:1065 [sdkCandidate]

Quote: `return client_id, _invalid_client(method == "client_secret_basic")`

[SDK] The WWW-Authenticate: Basic header on a 401 invalid_client response depends on the STORED method, not on the scheme the caller actually used. RFC 6749 section 5.2 says: if the client tried to authenticate with the Authorization header, the server MUST return 401 with a WWW-Authenticate header that matches that scheme. Three cases break this: a client_secret_post client that sends Basic (line 1065), a public client that sends Basic (line 1054), and a Basic/form client_id mismatch (line 1047). All three return 401 with no WWW-Authenticate.

Fix: Pass `basic is not None` (the scheme the caller presented) into _invalid_client, OR-ed with the stored method being client_secret_basic, at every return in _authenticate_client (lines 1047, 1054, 1063, 1065). Extend test_bad_secret_fails_everywhere to assert www-authenticate starts with 'Basic' whenever the Basic header was sent, whatever the registered method.

Codify: An invalid_client 401 must carry a WWW-Authenticate challenge for the scheme the caller presented, not the scheme it registered with.

## RT-004 (medium) — agent_sdk/routes/oauth.py:210 [sdkCandidate]

Quote: `"revocation_endpoint": f"{issuer}/oauth/revoke",`

[SDK] The RFC 8414 metadata advertises revocation_endpoint but leaves out revocation_endpoint_auth_methods_supported. RFC 8414 section 2 says the default is then client_secret_basic only. GH-222 now lets /oauth/revoke accept none, client_secret_post and client_secret_basic, each bound to the stored method. A strict client registered as client_secret_post, or as public, reads the default, sends Basic, and gets 401 invalid_client.

Fix: Add "revocation_endpoint_auth_methods_supported": list(_AUTH_METHODS) to the metadata dict, re-capture the GH-152 golden, assert the field in tests/test_gh222_confidential_dcr.py::test_metadata, and mention it in the CHANGELOG/DESIGN GH-222 text.

## RT-005 (medium) — agent_sdk/routes/oauth.py:1053 [sdkCandidate]

Quote: `if form_secret is not None or basic is not None:`

[SDK] Backward-compatibility break for existing public clients. _parse_form keeps blank values (keep_blank_values=True). So a public client that sends `client_secret=` (empty), or `Authorization: Basic base64(client_id:)` with an empty password, now gets 401 invalid_client on /oauth/token and /oauth/revoke. Before GH-222 it succeeded. Several OAuth libraries send exactly these shapes for public clients, so already-connected connectors would stop refreshing after upgrade.

Fix: For method 'none', treat an empty form client_secret and a Basic header with an empty secret (whose id matches the form client_id) as 'no secret presented'. Reject only a non-empty secret. Add regression tests for both shapes on token, refresh and revoke.

## RT-006 (low) — tests/test_gh222_confidential_dcr.py:241 [sdkCandidate]

Quote: `async def test_confidential_client_eviction_and_consent_same(client):`

[SDK] The AC says the one-time-consent shortcut must behave the same for confidential clients. This test only covers eviction protection after mark_consented. It never drives GET /oauth/authorize with oauth_one_time_consent enabled for a confidential client, so the shortcut path is not covered for confidential records.

Fix: Add a test: enable oauth_one_time_consent, register a confidential client, mark_consented, then GET /oauth/authorize. Assert the auto-approve redirect carries a code, then exchange that code using the client's secret.

## RT-007 (low) — agent_sdk/routes/oauth.py:1042 [sdkCandidate]

Quote: `through (the grant lookup rejects it) so existence is not disclosed here.`

[SDK] The docstring says client existence is not disclosed, but the endpoints act as an existence oracle. A known client_id with a wrong or unexpected secret gets 401 invalid_client. An unknown client_id gets 400 invalid_grant on /oauth/token, and 200 on /oauth/revoke. The claim is false, and it hides the gap described in RT-002.

Fix: Correct the docstring, or (preferably, together with RT-002) answer unknown client_ids with the same 401 invalid_client as a failed authentication, so the replies no longer reveal whether a client exists.

## RT-008 (low) — agent_sdk/routes/oauth.py:1179 [sdkCandidate]

Quote: `return auth_error  # type: ignore[return-value]`

[SDK] The type: ignore comment is unused: auth_error is already a JSONResponse, which matches the return type. `mypy agent_sdk/routes/oauth.py --warn-unused-ignores` reports 'Unused "type: ignore" comment [unused-ignore]' at this line.

Fix: Drop the `# type: ignore[return-value]` comment.
