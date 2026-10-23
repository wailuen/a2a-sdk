# w060 — unit:G2 — deferred medium/low findings

- Wave: w060
- Scope: unit:G2
- Date: 2026-10-23

Non-blocking — these did not block w060's archive. Address opportunistically or fold into a future wave.

## RT-001 (medium) — docs/deployment.md:279 [sdkCandidate]

Quote: "`FORWARDED_ALLOW_IPS=10.0.0.0/16`. Use the same values as"

[SDK] The new GH-218 section tells operators to give AGENT_SDK_TRUSTED_PROXIES 'the same values' as the CIDR example FORWARDED_ALLOW_IPS=10.0.0.0/16, but AGENT_SDK_TRUSTED_PROXIES cannot take that value. It is a pydantic list[str] (agent_sdk/config.py:166), so the env var must be a JSON list: AGENT_SDK_TRUSTED_PROXIES=10.0.0.0/16 or '10.0.0.5,10.0.0.6' raises SettingsError at boot (verified). And agent_sdk/common/limits.py:48-51 (client_ip) matches by exact string, so '["10.0.0.0/16"]' parses but never matches a peer: client_ip('10.0.0.5','1.2.3.4',['10.0.0.0/16']) returns '10.0.0.5' (verified). The claim that this makes 'uvicorn and the rate limiter agree' is also wrong. Once uvicorn trusts the gateway, it rewrites request.client to the real client, so the peer client_ip sees is never the gateway and AGENT_SDK_TRUSTED_PROXIES is never used. An operator who follows the doc as written gets a boot crash or a setting that silently does nothing.

Fix: Rewrite the paragraph. (a) FORWARDED_ALLOW_IPS is a comma-separated string that may hold CIDR ranges (uvicorn >=0.31). (b) AGENT_SDK_TRUSTED_PROXIES is a JSON list of exact IP addresses, e.g. AGENT_SDK_TRUSTED_PROXIES='["10.0.0.5"]', with no ranges. (c) Once FORWARDED_ALLOW_IPS covers the gateway, uvicorn already resolves the client address, and AGENT_SDK_TRUSTED_PROXIES matters only when uvicorn does not trust the gateway. Drop 'use the same values'. Optionally file an SDK issue to add CIDR matching (ipaddress.ip_network) and comma-separated parsing to client_ip and the trusted_proxies setting.

Codify: Before a doc says two settings take 'the same values', check that both parse the same format (JSON list vs comma string) and match the same way (exact IP vs CIDR).

## RT-002 (medium) — docs/security.md:82 [sdkCandidate]

Quote: "`FORWARDED_ALLOW_IPS` to the same range and never to `*`: see"

[SDK] The new cross-link in 'Rate limiting and proxies' tells readers to set FORWARDED_ALLOW_IPS 'to the same range' as AGENT_SDK_TRUSTED_PROXIES. That setting holds no ranges: it is an exact-match list of IPs (agent_sdk/common/limits.py:48 `peer_host in trusted_proxies`). The section also still does not document the env format (JSON list), so the RT-001 mistake repeats in the security doc.

Fix: Replace 'to the same range' with wording that matches the code. For example: 'also set uvicorn's FORWARDED_ALLOW_IPS to cover your gateway (never `*`)'. Add one sentence: AGENT_SDK_TRUSTED_PROXIES is a JSON list of exact proxy IPs, e.g. '["10.0.0.5"]', and CIDR ranges are not matched.

Codify: Security docs describing client-IP trust must state each setting's exact format and matching rule, checked against config.py and limits.py.

## RT-003 (low) — docs/deployment.md:279 [sdkCandidate]

Quote: "`FORWARDED_ALLOW_IPS=10.0.0.0/16`. Use the same values as"

[SDK] The CIDR example FORWARDED_ALLOW_IPS=10.0.0.0/16 only works on uvicorn 0.31.0 and later. Wheels checked: 0.27.0, 0.29.0, 0.30.0 and 0.30.6 have no ipaddress handling in uvicorn/middleware/proxy_headers.py; 0.31.0 has it. The SDK still allows uvicorn>=0.27 (pyproject.toml:15). On 0.27-0.30.x the range is compared as a literal string, so the gateway is never trusted and every client shares the gateway's rate-limit bucket. Nothing warns about this.

Fix: Add to the paragraph: 'CIDR ranges need uvicorn >= 0.31; on older uvicorn list exact gateway IPs.' Or raise the SDK floor to uvicorn>=0.31 in pyproject.toml, with a CHANGELOG line.

Codify: A deployment-doc example that uses a dependency feature must name the minimum version, or the SDK floor must be raised to match.
