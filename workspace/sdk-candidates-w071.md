# SDK issue candidates — w071 (2026-11-10)

These critical/high findings from wave w071 are classified as
SDK-level. Status is re-checked against the final tree: fixed-in-wave candidates were
already fixed by this wave; run `/sdk-issue-scan` on the still-open ones to file them on
`wailuen/a2a-sdk`. One confirmation per filing — nothing is filed automatically.

## Candidate 1: The GH-276 tests that check nothing stays bound after an admin try request cannot fail. The helper `_nothing_bound()` reads the context variables from the test's own task, but the app runs the request in a copied context. With `admin_mod.unbind_identity` and `forwarding.unbind` patched to do nothing (the same as removing the new `finally` block in agent_sdk/routes/admin.py), test_admin_try_binds_admin_identity, test_admin_try_unbinds_on_agent_error_and_timeout and test_admin_try_forwarded_credentials_via_adapter still pass. The second request in test (4) sends no header, so it reads None whether or not the first value leaked. Result: the identity and forwarded-credential unbinding in the admin try route has no real test guarding it. Fix: spy on the bind and unbind calls and check that each bind token is unbound exactly once on every exit path, or probe from a hook that runs after the finally block (such as `admin_mod._safe_result`).
- Severity: high
- Component: sdk/console
- File: tests/test_gh185_current_identity.py
- Status: fixed-in-wave
- Rationale: The test guards SDK code in agent_sdk/routes/admin.py (the admin test-console try endpoint), where it binds caller identity and forwarded credentials. It is an SDK test, not agent-domain code. A leak here could carry one caller's identity or credentials into another request, so a test that cannot fail is a real SDK gap, not wave-process hygiene.
