wave: w059
scope: unit:G3
group: G3
date: 2026-10-22

Non-blocking — these did not block w059's archive. Address opportunistically or fold into a future wave.

Deduped by file + description across every redteam round for unit G3. Where several rounds raised the
same finding, the entries are merged into one, the strongest severity is kept, and the extra detail from each
round is folded in. The IDs below are renumbered for this note; they do not match any single round's IDs.
Context: GH-213 (A2A supportedCatalogIds negotiation) and GH-219 (agent card oauth2 security scheme).

## Findings

### RT-001
- severity: medium
- file: tests/test_gh213_supported_catalog_ids.py
- sdkCandidate: true
- description: The GH-213 AC says an A2A message with `metadata.a2uiClientCapabilities = {supportedCatalogIds: [domain]}` plus the `X-A2A-Extensions` header gives `allows(DomainModel)` true AND the domain surface is emitted. test_a2a_route_resolves_supported_catalog_ids (~line 57) and test_a2a_route_resolves_v09_nested_supported_catalog_ids stop at `_capabilities(...).allows(_Domain)` on SimpleNamespace stand-ins. No request reaches the A2A route and no DataPart with the domain catalogId is checked (tests/test_gh180_a2a_catalog_negotiation.py does not cover it either). A regression in the emit path would pass. (Raised in 4 rounds.)
- fix: Add an end-to-end test. Register a tool that emits a domain ContentModel, drive it with FakeModelClient through `POST /v1/message:send` (or `:stream`) with `X-A2A-Extensions: <A2UI_EXTENSION_URI>` and `metadata.a2uiClientCapabilities.supportedCatalogIds=[DOMAIN]`; repeat with the nested `{"v0.9": {...}}` form. Assert the artifact holds an A2UI DataPart whose `data.messages` has a createSurface with `catalogId == DOMAIN`. Add a negative control (no key / no header) that gets only the TextPart fallback.
- codify: A todo AC that says 'X is emitted' needs an end-to-end assertion on the wire output, not just a unit check on the gate predicate.

### RT-002
- severity: medium
- file: tests/test_gh219_agent_card_oauth2.py
- sdkCandidate: true
- description: test_card_still_validates_against_a2a_model (~line 33-34) claims the GH-219 AC 'card still validates against the A2A v0.3.0 model', but `AgentCard.security_schemes` is typed `dict[str, Any] | None` (agent_sdk/models/a2a.py:256). `model_validate` accepts any oauth2 shape: missing `flows`/`scopes`, misspelled `tokenURL`/`oauth2MetadataURL`, or `openIdConnectUrl` on an oauth2 scheme. The hand-written oauth2 dict in agent_card.py:219-229 has no structural check against A2A v0.3.0 §4 (OAuth2SecurityScheme needs type+flows; AuthorizationCodeOAuthFlow needs authorizationUrl, tokenUrl, scopes). (Raised in 3 rounds.)
- fix: Preferred: add typed v0.3.0 models to agent_sdk/models/a2a.py — discriminated union on `type` (http, apiKey, oauth2, openIdConnect, mutualTLS), OAuthFlows, AuthorizationCodeOAuthFlow, `extra='forbid'` — and type `securitySchemes` as `dict[str, SecurityScheme]` (SDK API change: own todo + CHANGELOG). Minimum: in the test, assert exact key sets against harness/reference/a2a-protocol-0_3_0.md §4 — oauth2 scheme `{type, oauth2MetadataUrl, flows}`, flows only `authorizationCode`, which has exactly `{authorizationUrl, tokenUrl, scopes}` with scopes a dict; every URL absolute under resolved_base_url.
- codify: Claiming 'validates against the model' is vacuous when the model field is dict[str, Any]; assert the spec shape explicitly or type the field.

### RT-003
- severity: medium
- file: tests/test_gh219_agent_card_oauth2.py
- sdkCandidate: true
- description: test_extended_card_security_matches_public_when_advertised (~line 47-49) is circular. It compares the public card response with `app.state.agent_card`, the very dict that route serves, so it can never fail. It never calls the authenticated extended card route `GET /v1/card` (which returns -32007 not-configured). The SI-5 AC 'authenticated extended card's securitySchemes/security equal the public card's' is claimed, not tested; the name says 'when advertised' while the card is NOT advertised. (Raised in 4 rounds, medium/low.)
- fix: Call `GET /v1/card`: assert 401 without credentials, and with a valid bearer assert the -32007 not-configured error and no card body; assert `supportsAuthenticatedExtendedCard` is False. Add a guard: if the response is ever a card, its securitySchemes/security must equal the public card's (or derive the extended card from the same build_agent_card() output). Rename, e.g. test_no_extended_card_so_security_cannot_diverge.

### RT-004
- severity: medium
- file: DESIGN.md, docs/protocols.md, CHANGELOG.md
- sdkCandidate: true
- description: GH-219 changed the card's advertised auth surface, but DESIGN.md §4.5 'Agent card' (~lines 247-257) and the docs/protocols.md '## Agent card' paragraph (~lines 156-162) list protocolVersion, transport, extensions, x-sdk, x-agui and say nothing about securitySchemes/security. The bearer + oauth2 pair, URLs from resolved_base_url only (SI-5), and no openIdConnect even with AGENT_SDK_OAUTH_IDP=oidc exist only in a docstring, a todo and the CHANGELOG. Integrators cannot learn from the docs that OAuth is discoverable from the card. (Raised in 3 rounds, medium/low.)
- fix: Add a DESIGN.md §4.5 bullet: `securitySchemes` = {bearer: http/bearer (API key or SDK-issued token), oauth2: authorizationCode flow at `<base>/oauth/authorize` and `<base>/oauth/token`, `oauth2MetadataUrl` `<base>/.well-known/oauth-authorization-server` (RFC 8414), scopes {}}; `security` = [{bearer:[]},{oauth2:[]}] (either is enough); URLs from resolved_base_url (== OAuthTokenStore.issuer / PUBLIC_URL), never request headers; no openIdConnect scheme because the IdP sits upstream of the SDK's own AS (GH-219). Add one matching sentence to docs/protocols.md, and add both files to the GH-219 CHANGELOG 'Changed:' list.
- codify: A change to a public wire shape lands in DESIGN.md's section for that surface, not only in the code docstring and CHANGELOG.

### RT-005
- severity: low
- file: agent_sdk/a2ui/translator.py
- sdkCandidate: true
- description: from_metadata() (~lines 91-98) treats any non-empty list as usable, then `str()`-coerces each element (`[str(c) for c in catalogs]`). The GH-213 AC asks for 'a non-empty list[str]'. With `{"catalogs": [null], "supportedCatalogIds": [DOMAIN]}`, catalogs=["None"] wins precedence, the valid supportedCatalogIds is never consulted, and domain surfaces are silently gated off; `[{}]`, `[1]`, `[{"id": ...}]` become garbage ids. There is also no cap on entry count or length on untrusted client metadata copied per request (LRN-386). (Raised in 3 rounds.)
- fix: Normalise each candidate before choosing: `usable = [c for c in cand if isinstance(c, str) and c.strip()]` when `isinstance(cand, list)`; cap count (e.g. 64) and per-entry length (e.g. 256); take the first candidate whose usable list is non-empty, else fall through as an empty list does today. Apply to `catalogs` and both `supportedCatalogIds` locations. Add parametrized tests: catalogs=[None]/[1]/[{}]/[''] fall through to supportedCatalogIds; mixed lists keep only string ids; oversized lists are capped.

### RT-006
- severity: low
- file: tests/test_gh219_agent_card_oauth2.py
- description: Line 14: the GH-219 AC 'No openIdConnect scheme, even when AGENT_SDK_OAUTH_IDP=oidc' is checked only under default settings (oauth_idp unset). A later branch that adds openIdConnect when the IdP is on would not be caught.
- fix: Add a test that calls build_agent_card() with settings having oauth_idp='oidc' (plus required idp issuer/client fields). Assert no scheme has type 'openIdConnect' and securitySchemes equals the default-settings card's.

### RT-007
- severity: low
- file: CHANGELOG.md
- description: The GH-219 entry sits under '### Fixed', but it adds a new public card security scheme and changes the `security` array. The wave header (workspace/todos/active/w059-gh-issues.md line 5) cites 'new card security scheme' as a reason for the 0.18.0 minor bump. Filing an additive public surface under Fixed misstates the change kind (LRN-423).
- fix: Move the GH-219 bullet from '### Fixed' to '### Added' (or '### Changed'), keeping its migration note about exact-equality securitySchemes comparisons.
