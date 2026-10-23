# w060 — phase redteam: deferred medium/low findings

- wave: w060
- scope: phase
- date: 2026-10-23

Non-blocking — these did not block w060's archive. Address opportunistically or fold into a future wave.

## RT-004 (medium) [SDK] — agent_sdk/routes/oauth.py:1065
- quote: `return client_id, _invalid_client(method == "client_secret_basic")`
- issue: RFC 6749 §5.2 says a client that authenticated via the Authorization header MUST get 401 with a matching WWW-Authenticate, but the header is sent only when the STORED method is client_secret_basic; a post-registered or public client that sends `Authorization: Basic`, and the Basic-id vs form-client_id mismatch path (line 1047), get 401 with no WWW-Authenticate.
- fix: Pass `basic is not None or method == "client_secret_basic"` to _invalid_client on every invalid_client return in _authenticate_client (mismatch, method none with Basic, wrong-method), and extend test_bad_secret_fails_everywhere to assert the Basic challenge whenever the request carried a Basic header.
- sdkCandidate: true

## RT-005 (medium) [SDK] — agent_sdk/routes/oauth.py:1053 — FIXED before v0.18.0 tag (empty secret = not presented)
- quote: `if form_secret is not None or basic is not None:`
- issue: Backward-compat break for existing public clients: a public client that sends an empty `client_secret=` form field (common in generic OAuth libraries) was accepted before GH-222 and now gets 401 invalid_client on token, refresh and revoke; the ruling's 'public client that presents a secret' does not require rejecting an empty value, and no test pins this case.
- fix: Treat an empty form `client_secret` as absent for public clients (e.g. `if (form_secret not in (None, "")) or basic is not None`), and add a test that a public client sending `client_secret=` still completes code -> token -> refresh.
- sdkCandidate: true

## RT-006 (medium) [SDK] — harness/workflows/wave-cycle.js:1470
- quote: `'        return gh(["label", "create", name, "-R", REPO, "--force"]).returncode == 0',`
- issue: `gh label create <name> --force` with no --color picks a random color and, per gh's own help, updates the existing label, so every auto-file run recolors existing wailuen/a2a-sdk labels (security, protocol/*, ...); and when label creation is refused (any non-collaborator running from an agent repo) the issue is filed with no `auto-filed` label, breaking the ruling's 'with an auto-filed label' requirement. Same code in .claude/workflows/sdk-wave.js and the template copy.
- fix: Check for the label first (`gh label list -R REPO --search name --json name`) and create it only when missing, with a fixed --color and no --force. If the auto-filed label cannot be applied, do not file: leave the candidate in sdk-candidates.md for /sdk-issue-scan. Update test_filer_files_without_labels_when_labels_are_refused accordingly and keep both runners in parity.
- sdkCandidate: true

## RT-007 (medium) — workspace/todos/deferred/w050-group-G4-medium-low.md:15
- quote: `- status: card half closed by GH-219 (the agent card no longer carries `x-sdk.outputSchema`, so it cannot drift); the MCP `tools/list` outputSchema half stays open.`
- issue: The GH-219 status line was put on RT-001, which is about the DocumentItem model_serializer round-trip and has nothing to do with the card; the card outputSchema drift item is RT-002. RT-001 now wrongly reads as half closed and RT-002 is not updated.
- fix: Move the status line from RT-001 to RT-002 (the card x-sdk.outputSchema / tools/list drift item) and leave RT-001 untouched.
- sdkCandidate: false

## RT-008 (medium) — tests/test_gh219_card_remainders.py:87
- quote: `assert card_bytes > 0`
- issue: GH-219 AC 'card byte size for the example agent shrank' is not tested: test_card_bytes_no_longer_carry_output_schemas never compares to a pre-change size (it asserts dropped > 0 and card_bytes > 0), and test_blank_description_still_falls_back_to_display_name only asserts the description is truthy, not equal to display_name.
- fix: Build the pre-change card size by re-adding each entry.output_schema() under x-sdk.outputSchema (or rebuild the skill dicts with it) and assert the served card is smaller by at least the dropped bytes; assert card['description'] == settings.display_name when AGENT_DESCRIPTION is blank.
- sdkCandidate: false

## RT-009 (low) [SDK] — harness/workflows/wave-cycle.js:1560
- quote: `return hits.length === 1 ? hits[0] : null`
- issue: toCodeify is deduped by file+description only, so the same finding re-raised across rounds with a reworded description yields 2+ hits with identical id/file/quote; originalFinding then returns null and the candidate can never be marked fixed-in-wave, even though every hit has the same quote and would give the same stale result. Same in .claude/workflows/sdk-wave.js.
- fix: Accept multiple hits when they share file and quote (they are the same subject for the stale check): return hits[0] when hits.length >= 1 and every hit has the same file+quote; keep null only for zero hits.
- sdkCandidate: true

## RT-010 (low) [SDK] — agent_sdk/auth/oauth_tokens.py:208
- quote: `return method if isinstance(method, str) else "none"`
- issue: client_auth_method fails open: a stored record whose token_endpoint_auth_method is missing or not a string is treated as a public client, so a confidential record (one with client_secret_hash) that is damaged would accept token and revoke calls with no secret.
- fix: Return "none" only when the field is absent AND the record has no client_secret_hash; if client_secret_hash is present, or the field is a non-string, return a value outside _AUTH_METHODS so _authenticate_client rejects with invalid_client.
- sdkCandidate: true
