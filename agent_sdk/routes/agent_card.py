"""Agent card assembly + discovery routes (DESIGN.md §4.5).

The SDK assembles the card; teams never hand-write card JSON. Served at the
A2A v0.3.0 well-known path with an ETag/conditional GET, and byte-identical
at the legacy ``/.well-known/agent.json`` alias. The authenticated
extended-card method is served defensively and answers ``-32007``.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Request, Response

from ..a2ui.catalog import a2ui_extension, supported_catalogs
from ..agent.registry import ToolRegistry
from ..auth.identity import Identity
from ..auth.middleware import require_identity
from ..common.etag import etag_for, matches
from ..common.wire_errors import a2a_error
from ..config import BaseAgentSettings
from ..credentials.card import credential_forwarding_extension
from ..credentials.fields import CredentialField
from ..models.a2a import AgentCapabilities, AgentCard, AgentExtension, AgentSkill
from ..models.errors import A2A_AUTHENTICATED_EXTENDED_CARD_NOT_CONFIGURED

router = APIRouter()

# Frozen §5.3 CUSTOM event names — the card's x-agui.customEvents list and
# the console's routing table are asserted equal by a unit test.
CUSTOM_EVENTS = (
    "AGENT_ARTIFACT",
    "A2UI_UPDATE",
    "AGENT_PROGRESS",
    "AGENT_NOTE",
    "TOOL_PROGRESS",
)

# P6-01: AG-UI customEvents must be objects with name + valueSchema, not flat
# strings.  The name set is identical to CUSTOM_EVENTS (routing table parity).
_CUSTOM_EVENT_SCHEMAS = [
    {
        "name": "AGENT_ARTIFACT",
        "valueSchema": {
            "type": "object",
            "properties": {
                "dataType": {"type": "string"},
                "toolName": {"type": "string"},
                "data": {"type": "object"},
            },
        },
    },
    {
        "name": "A2UI_UPDATE",
        "valueSchema": {
            "type": "object",
            "properties": {
                "messages": {"type": "array", "items": {"type": "object"}},
            },
        },
    },
    {
        "name": "AGENT_PROGRESS",
        "valueSchema": {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
            },
        },
    },
    {
        "name": "AGENT_NOTE",
        "valueSchema": {
            "type": "object",
            "properties": {
                "note": {"type": "string"},
            },
        },
    },
    {
        "name": "TOOL_PROGRESS",
        "valueSchema": {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "toolName": {"type": "string"},
            },
        },
    },
]


def _skill_for(entry: Any) -> AgentSkill:
    emits = entry.decl.emits
    members = entry.decl.emits_types
    x_sdk: dict[str, Any] = {
        "tier": entry.tier,
        "inputSchema": entry.input_schema(),
    }
    if isinstance(emits, tuple):
        x_sdk["emits"] = [getattr(m, "data_type", m.__name__) for m in members]
    elif emits is not None:
        x_sdk["emits"] = getattr(emits, "data_type", emits.__name__)
    return AgentSkill.model_validate({
        "id": entry.name,
        "name": entry.name,
        "description": entry.description,
        "tags": entry.decl.tags,
        "x-sdk": x_sdk,
    })


def task_error_extension() -> AgentExtension:
    """SDK extension: TaskStatus carries an optional WireError on failure.

    This field is not part of the A2A v0.3.0 spec; spec-compliant consumers
    may safely ignore it.  Declared so clients that understand it can surface
    structured error detail without polling or guessing.
    """
    return AgentExtension(
        uri="https://agent-sdk.dev/extensions/task-error/v1",
        required=False,
        description=(
            "TaskStatus carries an optional error field (WireError) on failure"
            " — not in A2A v0.3.0 spec; safe to ignore if unknown"
        ),
    )


def compute_a2ui_enabled(allowed_components: list[str] | None, emits: list[type]) -> bool:
    """The single A2UI on/off gate (GH-257); computed once in ``build_app()``."""
    return bool(supported_catalogs(allowed_components, emits))


def build_agent_card(
    settings: BaseAgentSettings,
    registry: ToolRegistry,
    credential_fields: dict[str, list[CredentialField]] | None = None,
    *,
    allowed_components: list[str] | None = None,
    a2ui_enabled: bool = False,
    emits: list[type] | None = None,
) -> dict[str, Any]:
    """Assemble the wire-ready card dict once at boot (app.state.agent_card).

    ``credential_fields`` (source_name → declared fields) drives the optional
    credential-forwarding extension; the vendor key is NOT an agent
    securityScheme (a2a-advisor), but the SDK's own OAuth authorization
    server IS one: the card advertises ``oauth2`` alongside ``bearer``
    (GH-219). Its URLs come from ``resolved_base_url`` (the same origin as
    ``OAuthTokenStore.issuer``), never from request headers. No
    ``openIdConnect`` scheme, even with ``AGENT_SDK_OAUTH_IDP=oidc``.

    ``allowed_components`` (SC-D2): when set, the A2UI extension only
    advertises catalog IDs for the listed component types. Catalog IDs come
    from the registered tools' ``emits`` types (GH-188). With no catalog to
    advertise the A2UI extension is left off the card (GH-249).

    ``a2ui_enabled`` (GH-257) is the app's single gate; the card never
    recomputes it. ``emits`` is the flattened emits list, built from the
    registry when omitted.
    """
    base_url = settings.resolved_base_url
    if emits is None:
        emits = [m for e in registry.all() for m in e.decl.emits_types]
    extensions = []
    output_modes = ["text/plain", "application/json"]
    if a2ui_enabled:
        extensions.append(a2ui_extension(allowed_components, emits))
        output_modes.append("application/a2ui+json")
    extensions += [
        AgentExtension(
            uri="https://agent-sdk.dev/extensions/ag-ui-run/v1",
            description="AG-UI streaming run endpoint (SSE)",
            required=False,
            params={"endpoint": f"{base_url}/ag-ui/run"},
        ),
        task_error_extension(),
    ]
    cred_ext = credential_forwarding_extension(credential_fields or {})
    if cred_ext is not None:
        extensions.append(cred_ext)
    _desc_stripped = settings.agent_description.strip()
    # A2A §3.1 requires description to be a human-readable string — "" is
    # spec-marginal. When description is blank, fall back to display_name for
    # all cases: placeholder names get the neutral sentinel ("agent-sdk-agent"),
    # real names get the name itself. Never emit empty-string or raw placeholder.
    _description = _desc_stripped or settings.display_name
    card = AgentCard.model_validate({
        # name is an A2A v0.3.0 REQUIRED identity field — normalize the
        # placeholder/blank/whitespace agent_name via display_name, identically
        # to MCP serverInfo.name/title and /health, so the card never advertises
        # the raw placeholder (RT-001).
        "name": settings.display_name,
        "description": _description,
        "url": base_url,  # HTTP+JSON transport: clients append /v1/message:send per §2 (not /)
        "version": settings.agent_version,
        "capabilities": AgentCapabilities(
            streaming=True,
            pushNotifications=False,
            extensions=extensions,
        ),
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": output_modes,
        # Tier-2 tools are A2A-only (§5.6); MCP tools/list exposes tier-1 only.
        # The card must not advertise tools MCP consumers cannot call (LRN-094).
        "skills": [_skill_for(e) for e in registry.tier1()],
        "supportsAuthenticatedExtendedCard": False,
        "securitySchemes": {
            "bearer": {"type": "http", "scheme": "bearer"},
            "oauth2": {
                "type": "oauth2",
                "oauth2MetadataUrl": f"{base_url}/.well-known/oauth-authorization-server",
                "flows": {
                    "authorizationCode": {
                        "authorizationUrl": f"{base_url}/oauth/authorize",
                        "tokenUrl": f"{base_url}/oauth/token",
                        "scopes": {},
                    }
                },
            },
        },
        "security": [{"bearer": []}, {"oauth2": []}],
        "x-agui": {
            "transport": "sse",
            "endpoint": f"{base_url}/ag-ui/run",
            "customEvents": _CUSTOM_EVENT_SCHEMAS,
        },
    })
    return card.wire()


def _card_response(request: Request) -> Response:
    payload = request.app.state.agent_card
    etag = etag_for(payload)
    if matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers={"ETag": etag})
    body = json.dumps(payload, separators=(",", ":")).encode()
    return Response(
        content=body,
        media_type="application/json",
        headers={"ETag": etag, "Cache-Control": "public, max-age=300"},
    )


@router.get("/.well-known/agent-card.json")
async def agent_card(request: Request) -> Response:
    return _card_response(request)


@router.get("/.well-known/agent.json")
async def agent_card_legacy(request: Request) -> Response:
    # byte-identical legacy alias (§4.5)
    return _card_response(request)


@router.get("/v1/card")
async def extended_card(identity: Identity = Depends(require_identity)) -> Any:
    # SC-A3: auth-gate the extended card per A2A §1 intent.
    # Even when not configured, the route requires a valid identity (401 before 501).
    return a2a_error(
        A2A_AUTHENTICATED_EXTENDED_CARD_NOT_CONFIGURED,
        "authenticated extended card is not configured",
    )
