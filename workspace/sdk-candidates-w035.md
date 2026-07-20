# SDK issue candidates — w035 (2026-07-20)

Run `/sdk-issue-scan` to review and file as GitHub issues on `wailuen/a2a-sdk`.

Note: this file originally listed 7 candidates surfaced across w035's redteam
rounds. Candidates 1–6 (all in `agent_sdk/routes/oauth.py`'s CSP handling and
`.claude/workflows/sdk-wave.js`'s import-resolution ladder) described
intermediate states from early-round findings that were fixed later in the
*same* wave by RT-001 through RT-004 — verified directly against current code
(`_redirect_security_headers`/`_validated_origin` in oauth.py, the four-way
resolver ladder in sdk-wave.js) and the passing regression tests
(`tests/test_oauth_flow.py::test_valid_redirect_uri_rejects_csp_significant_netloc`,
`test_dcr_rejects_csp_injection_redirect_uri`, `test_valid_redirect_uri_rejects_ipv6_literal`,
etc.). They were pruned here so `/sdk-issue-scan` doesn't file already-fixed
findings as new issues. Only the genuinely open finding remains below.

## Candidate 1: `sdk-wave.js` classifies `agent_sdk/routes/oauth.py` as `MCP_SURFACE`-only, so a wave touching oauth.py only dispatches the mcp-advisor and never the a2a-advisor or ag-ui-advisor — but oauth.py's `OAuthTokenStore.verify` is the shared auth backend consumed via `require_identity` by every protected A2A and AG-UI endpoint (its own docstring documents PRM payloads for `/v1/` and `/ag-ui/` surfaces). A wave editing oauth.py's audience validation, PRM payloads, or token minting can silently break A2A or AG-UI auth while the protocol-audit gate reports only an MCP finding set, and no test in tests/ asserts surface-array membership to catch a regression.
- Severity: high
- Component: harness/workflow
- File: `.claude/workflows/sdk-wave.js` (lines 23-25: `A2A_SURFACE`, `MCP_SURFACE`, `AGUI_SURFACE`)
- Rationale: The misclassification lives in the MCP_SURFACE/A2A_SURFACE/AGUI_SURFACE arrays inside `.claude/workflows/sdk-wave.js`, which govern which protocol advisors a wave dispatches — an SDK harness workflow defect with real cross-protocol (protocol/oauth, protocol/a2a, protocol/ag-ui) blast radius, but the fix and the bug both sit in the harness workflow file.
- Codified: `workspace/learning/LRN-132-protocol-surface-classification-by-blast-radius.md`
- Confirmed still open as of 2026-07-20 (not fixed in w035): `agent_sdk/routes/oauth.py` is present only in `MCP_SURFACE`, absent from `A2A_SURFACE` and `AGUI_SURFACE`.
