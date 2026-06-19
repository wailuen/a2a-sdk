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

from ..a2ui.catalog import a2ui_extension
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
CUSTOM_EVENTS = ("AGENT_ARTIFACT", "A2UI_UPDATE", "AGENT_PROGRESS", "AGENT_NOTE")

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
]


def _skill_for(entry: Any) -> AgentSkill:
    emits = entry.decl.emits
    x_sdk: dict[str, Any] = {
        "tier": entry.tier,
        "inputSchema": entry.input_schema(),
    }
    output_schema = entry.output_schema()
    if output_schema is not None:
        x_sdk["outputSchema"] = output_schema
    if emits is not None:
        x_sdk["emits"] = getattr(emits, "data_type", emits.__name__)
    return AgentSkill.model_validate({
        "id": entry.name,
        "name": entry.name,
        "description": entry.description,
        "tags": entry.decl.tags,
        "x-sdk": x_sdk,
    })


def build_agent_card(
    settings: BaseAgentSettings,
    registry: ToolRegistry,
    credential_fields: dict[str, list[CredentialField]] | None = None,
    *,
    allowed_components: list[str] | None = None,
) -> dict[str, Any]:
    """Assemble the wire-ready card dict once at boot (app.state.agent_card).

    ``credential_fields`` (source_name → declared fields) drives the optional
    credential-forwarding extension; the vendor key is NOT an agent
    securityScheme (a2a-advisor) — the card's own auth stays bearer-only.

    ``allowed_components`` (SC-D2): when set, the A2UI extension only
    advertises catalog IDs for the listed component types.
    """
    base_url = settings.resolved_base_url
    extensions = [
        a2ui_extension(allowed_components),
        AgentExtension(
            uri="urn:agui:run:v1",
            description="AG-UI streaming run endpoint (SSE)",
            required=False,
            params={"endpoint": f"{base_url}/ag-ui/run"},
        ),
    ]
    cred_ext = credential_forwarding_extension(credential_fields or {})
    if cred_ext is not None:
        extensions.append(cred_ext)
    card = AgentCard.model_validate({
        "name": settings.agent_name,
        "description": settings.agent_description or settings.agent_name,
        "url": base_url,  # HTTP+JSON transport: clients append /v1/message:send per §2 (not /)
        "version": settings.agent_version,
        "capabilities": AgentCapabilities(
            streaming=True,
            pushNotifications=False,
            extensions=extensions,
        ),
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain", "application/json", "application/a2ui+json"],
        "skills": [_skill_for(e) for e in registry.all()],
        "supportsAuthenticatedExtendedCard": False,
        "securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}},
        "security": [{"bearer": []}],
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
