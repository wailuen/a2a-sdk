# w071 — unit:G1 — deferred medium/low findings

- Wave: w071
- Scope: unit:G1
- Date: 2026-11-10

Non-blocking — these did not block w071's archive. Address opportunistically or fold into a future wave.

## MEDIUM

### RT-001 — tests/test_gh277_oauth_label.py:166
Quote: `new = store.rotate_refresh(old["refresh_token"], client_id=cid)`
- Description: GH-277 test (5) checks that the refresh-family label is cleared by calling OAuthTokenStore.rotate_refresh directly. It never sends POST /oauth/token with grant_type=refresh_token through build_app() over the ASGI transport, which the wave header requires "where a route is involved" (LRN-496). Its SI-2 log capture also sees only store-level log lines, not the token route's own logs. If the refresh route ever built the label itself, or went around rotate_refresh, the test would still pass.
- Fix: Reach the stale family through the real route. Register with client_name=NAME, mint a pair with label=NAME, then POST /oauth/token (grant_type=refresh_token, client_id=cid, refresh_token=...) through the ASGI client. Assert 200 and that store.verify(new access_token).label == f"oauth:{cid[:8]}". Capture logs across that HTTP call and assert that NAME, both refresh tokens and the full cid never appear. Do the same for the IdP-label family (label kept).
- Codify: A rotation or refresh behaviour fix must be tested through POST /oauth/token over build_app(), not by calling the store method directly.

## LOW

### RT-003 (SDK candidate) — agent_sdk/auth/oauth_tokens.py:474
Quote: `client = self.get_client(client_id) or {}`
- Description: The new `get_client` store read in `rotate_refresh` runs after the presented refresh token has already been marked rotated and saved (line 467). If that read throws (for example a transient Azure Table error), the client gets a 500 and keeps a token that is now marked rotated. Its retry then counts as reuse and revokes the whole family. The label decision does not depend on the tombstone write.
- Fix: Look up the client and work out `label` before `record["rotated"] = True` / `self._store.set(...)`, for example next to the bound-client check. Then a store failure in the lookup leaves the presented token usable.

### RT-002 / RT-004 (SDK candidate, merged) — tests/test_gh152_idp_off_regression.py:123
Quote: `assert "label" not in t.text and "Claude" not in t.text`
- Description: AC (6) says the token response bytes stay unchanged with IdP off. Test (6) checks only the sorted key names plus substring checks. Both substring checks would pass with or without the GH-277 change, because the token body never carried a label or "Claude". It does not compare `token_type`, the `expires_in` value, or the absent `scope` key, so a change to those, or a new field value, would not be caught.
- Fix: Replace access_token/refresh_token with fixed placeholders, then compare the serialised body to a golden `{"access_token":"A","token_type":"Bearer","expires_in":3600,"refresh_token":"R"}` (or a sha of it), matching the golden-hash style in this file. Or at least assert token_type == "Bearer", expires_in equals the configured access TTL, and both tokens are non-empty strings. Pin the Content-Type and Cache-Control/Pragma headers. Drop the vacuous "Claude" check.

### RT-005 / RT-003 (SDK candidate, merged) — tests/test_gh277_oauth_label.py:23
Quote: `_allowed,`
- Description: `_allowed` is imported from tests.test_gh152_idp_authorize_flow and never used. It is a plain helper, not a fixture, so the import is dead code. Separately, GH-276 test (4) (tests/test_gh185_current_identity.py:603) reads the value with `credential_or_none()`, while the AC names the adapter's `self.credential()` call.
- Fix: Remove `_allowed` from the import list. In try_cred, call `src.credential("api_key")` for the header case so the test exercises the AC's named path. Keep `credential_or_none` only for the no-header case if a None result is needed.

### RT-004 — CHANGELOG.md:12
- Description: The GH-277 entry sits under "### Fixed" and never says that `Identity.label` / `current_identity().label` visibly changes for downstream agents. Any agent that showed or keyed on the old client_name label (for example "Claude") will now see "oauth:<client_id[:8]>". The wave plan calls this a visible behaviour change, and the sibling GH-276 entry is flagged that way, but GH-277 is not.
- Fix: Add to the GH-277 bullet: "Visible behaviour change: tools that displayed `current_identity().label` for OAuth callers without IdP sign-in now see `oauth:<client_id[:8]>` instead of the client's `client_name`; use `Identity.user`/`subject` for identity, never the label." Or move or duplicate a short pointer under "### Changed".

### RT-005 — agent_sdk/routes/admin.py:582
Quote: `"""Direct entry.invoke (admin only). Tool failures return safe error`
- Description: The try_tool docstring was not updated for GH-276. It still says "Direct entry.invoke", but the route now binds the admin Identity and the X-Agent-Credentials forwarded credentials around invoke_any. That contract is new and visible to tools, and now appears only in an inline comment.
- Fix: Extend the docstring: "Binds the admin key's Identity (current_identity()) and X-Agent-Credentials forwarded credentials around invoke_any, as MCP tools/call does; both are unbound in finally on every exit (GH-276)."

Resolved 2026-11-12: all findings fixed by hand before release.
