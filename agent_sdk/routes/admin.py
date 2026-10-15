"""Admin APIs + console page serving (DESIGN.md §7, §7.1, §6).

The console shell (``GET /admin/console``) is served without auth — it is a
static page holding zero data; every data API under ``/admin/api/*`` requires
an admin API-key identity (``Depends(require_admin)``), and the page's JS
acquires the bearer on first run via the bootstrap-token flow (§6).

Invariants enforced here:

- **Strict CSP, no unsafe-inline anywhere**: the shell carries no inline
  scripts or ``style=`` attributes; all JS/CSS ships as static files under
  ``/admin/static/`` (so no nonce is needed).
- **Header-borne bearer only** — no cookies are set on any path.
- **Bootstrap mint** (§6): ``POST /admin/api/keys`` with a valid
  ``X-Bootstrap-Token`` mints the first key without an identity; the minted
  key is always admin. Every bootstrap-path request is loudly logged.
- **Credential namespace rules** (§6): the credentials API exposes adapter
  namespaces plus the dedicated Bedrock form (``NS_BEDROCK``); every other
  reserved namespace is unreachable. Values are write-only — the API reports
  set/unset booleans, never stored values.
- **Static shadowing**: ``/admin/static/{path}`` resolves against
  ``app.state.console_static_dirs`` in order (agent override dir first, SDK
  dir last), path-traversal safe (resolve + parent check, file-by-file).
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, HTMLResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel

from ..agent.loop import safe_validation_message
from ..agent.registry import ToolInputValidationError
from ..auth.middleware import AuthRuntime, _prm_challenge, require_admin, unauth_rate_limit
from ..common.redact import frame_locations, safe_line_text, sanitize_text
from ..credentials.fields import CredentialField, validate_credential_url
from ..credentials.store import NS_BEDROCK, NS_MODEL, NS_OAUTH_IDP, RESERVED_NAMESPACES, CredentialStore
from ..models.errors import AgentError, ErrorCategory
from ..sources import SourceAdapter

logger = logging.getLogger("agent_sdk.admin")

router = APIRouter()

_CONSOLE_DIR = Path(__file__).resolve().parent.parent / "console"
_TEMPLATE_DIR = _CONSOLE_DIR / "templates"
SDK_STATIC_DIR = _CONSOLE_DIR / "static"

# Exact policy per DESIGN.md §7 (frame-ancestors/base-uri are strictly
# tightening additions; §7 mandates DENY-framing for sensitive pages).
_CONSOLE_CSP = (
    "default-src 'none'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "connect-src 'self'; "
    "img-src 'self' data:; "
    "frame-ancestors 'none'; "
    "base-uri 'none'; "
    "form-action 'self'"
)

_MEDIA_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}

_HEALTH_CHECK_TIMEOUT = 5.0
# Per-tool execution timeouts (§8): tier 1 = 130s, tier 2 = 180s.
_TRY_TIMEOUTS = {1: 130.0, 2: 180.0}

# Dedicated model-backend credential form (§6 reserved namespace). LLM API keys
# are never stored in .env — they live here, seeded once via /admin → Model Backend.
_MODEL_FIELDS: tuple[CredentialField, ...] = (
    CredentialField(
        name="openai_api_key",
        label="OpenAI API key",
        secret=True,
        required=False,
        help_text="API key for openai.com or a compatible endpoint. Requires OPENAI_MODEL in .env.",
    ),
    CredentialField(
        name="azure_openai_api_key",
        label="Azure OpenAI API key",
        secret=True,
        required=False,
        help_text="API key for Azure OpenAI. Requires AZURE_OPENAI_ENDPOINT in .env.",
    ),
    CredentialField(
        name="anthropic_api_key",
        label="Anthropic / Claude API key",
        secret=True,
        required=False,
        help_text="API key for api.anthropic.com. Reserved for future Anthropic model-backend support.",
    ),
)

_OAUTH_IDP_FIELDS: tuple[CredentialField, ...] = (
    CredentialField(
        name="client_secret",
        label="IdP sign-in client secret",
        secret=True,
        required=False,
        help_text="Client secret of the app registration used for AGENT_SDK_OAUTH_IDP sign-in.",
    ),
)

# Dedicated Bedrock credential form (§6 reserved namespace).
_BEDROCK_FIELDS: tuple[CredentialField, ...] = (
    CredentialField(
        name="bearer_token",
        label="Bedrock API key (bearer token)",
        secret=True,
        required=False,
        help_text="Preferred: Amazon Bedrock API key. Checked first in the credential chain.",
    ),
    CredentialField(
        name="aws_access_key_id",
        label="AWS access key ID",
        secret=False,
        required=False,
        help_text="IAM static credentials (used when no Bedrock API key is set).",
    ),
    CredentialField(
        name="aws_secret_access_key",
        label="AWS secret access key",
        secret=True,
        required=False,
        help_text="Pairs with the access key ID. Falls back to the default AWS chain when unset.",
    ),
    CredentialField(
        name="aws_session_token",
        label="AWS session token",
        secret=True,
        required=False,
        help_text="Required only for STS / temporary credentials; pairs with the access key ID + secret. Leave blank for long-lived IAM keys.",
    ),
)

_jinja = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(("html", "xml")),
)


# ── request bodies ──


class KeyMintRequest(BaseModel):
    label: str = "console"
    admin: bool = False
    service: bool = False


class CredentialValue(BaseModel):
    value: str


# ── state accessors ──


def _auth(request: Request) -> AuthRuntime:
    return request.app.state.auth


def _adapters(request: Request) -> dict[type[SourceAdapter], SourceAdapter]:
    return request.app.state.adapters


def _credential_store(request: Request) -> CredentialStore:
    return request.app.state.credential_store


def _declared_fields(request: Request, adapter: SourceAdapter) -> list[CredentialField]:
    """CredentialFields declared via register_source(credentials=[...]).

    The app builder stashes them at ``app.state.credential_fields`` keyed by
    source_name; an adapter-class ``credential_fields`` attribute is honored
    as a fallback so hand-built apps degrade gracefully.
    """
    by_source = getattr(request.app.state, "credential_fields", None) or {}
    declared = by_source.get(adapter.source_name)
    if declared is None:
        declared = getattr(type(adapter), "credential_fields", None) or []
    return list(declared)


# ── console shell + static files ──


@router.get("/admin", response_class=HTMLResponse)
@router.get("/admin/console", response_class=HTMLResponse)
async def console_page(request: Request) -> HTMLResponse:
    """The single-page shell. NO auth on the page itself (it holds no data);
    the JS asks for a key / bootstrap token first-run."""
    settings = request.app.state.settings
    html = _jinja.get_template("console.html").render(
        agent_name=settings.agent_name,
        agent_version=settings.agent_version,
    )
    return HTMLResponse(
        html,
        headers={
            "Content-Security-Policy": _CONSOLE_CSP,
            "X-Frame-Options": "DENY",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Cache-Control": "no-store",
        },
    )


@router.get("/admin/static/{asset_path:path}")
async def console_static(asset_path: str, request: Request) -> FileResponse:
    """File-by-file shadowing across console_static_dirs (override dir
    first, SDK dir last). Traversal-safe: resolve + verify ancestry."""
    if not asset_path or "\x00" in asset_path or asset_path.startswith("/"):
        raise HTTPException(status_code=404, detail="not found")
    dirs: list[Path] = list(
        getattr(request.app.state, "console_static_dirs", None) or [SDK_STATIC_DIR]
    )
    for base in dirs:
        base = Path(base).resolve()
        candidate = (base / asset_path).resolve()
        if not candidate.is_relative_to(base):
            continue  # traversal attempt or symlink escape — never served
        if candidate.is_file():
            media_type = _MEDIA_TYPES.get(candidate.suffix.lower(), "application/octet-stream")
            return FileResponse(
                candidate,
                media_type=media_type,
                headers={
                    "Cache-Control": "no-cache",
                    "X-Content-Type-Options": "nosniff",
                },
            )
    raise HTTPException(status_code=404, detail="not found")


# ── API keys ──


@router.post("/admin/api/keys")
async def mint_key(request: Request, body: KeyMintRequest) -> dict[str, Any]:
    """Mint an API key. First-run special case (§6): a valid
    ``X-Bootstrap-Token`` mints without an identity — that key is admin.
    Plaintext is returned exactly once and never stored."""
    if body.admin and body.service:
        raise HTTPException(status_code=422, detail="a key cannot be both admin and service")
    auth = _auth(request)
    bootstrap_token = request.headers.get("x-bootstrap-token")
    if bootstrap_token is not None:
        # Unauthenticated path: per-IP rate limit before touching the token.
        unauth_rate_limit(request)
        if body.service:
            raise HTTPException(
                status_code=422, detail="the bootstrap token mints an admin key only"
            )
        logger.warning("bootstrap-path key mint attempted (label=%r)", body.label)
        if not auth.bootstrap.consume(bootstrap_token):
            logger.warning("bootstrap token rejected (expired, used, or wrong)")
            raise HTTPException(
                status_code=401,
                detail="invalid or expired bootstrap token",
                headers={"WWW-Authenticate": _prm_challenge(auth.prm_url)},
            )
        key_id, plaintext = auth.api_keys.mint(body.label, admin=True)
        logger.warning("bootstrap token consumed: first admin key %s minted", key_id)
        admin = True
    else:
        await require_admin(request)
        key_id, plaintext = auth.api_keys.mint(
            body.label, admin=body.admin, service=body.service
        )
        admin = body.admin
        if body.service:
            logger.warning("service key %s minted (label=%s)", key_id, safe_line_text(body.label))
    return {
        "key_id": key_id,
        "prefix": plaintext[:11],
        "label": body.label,
        "admin": admin,
        "service": body.service and not admin,
        "plaintext": plaintext,  # shown once — the store keeps only the hash
    }


@router.get("/admin/api/keys", dependencies=[Depends(require_admin)])
async def list_keys(request: Request) -> dict[str, Any]:
    keys = _auth(request).api_keys.list_keys()
    return {
        "keys": [
            {
                "key_id": k.key_id,
                "prefix": k.prefix,  # prefix-only display (§6)
                "label": k.label,
                "admin": k.admin,
                "service": k.service,
                "created_at": k.created_at,
                "last_used": k.last_used,
            }
            for k in sorted(keys, key=lambda k: k.created_at)
        ],
        "count": len(keys),
    }


@router.delete("/admin/api/keys/{key_id}", dependencies=[Depends(require_admin)])
async def revoke_key(key_id: str, request: Request) -> dict[str, Any]:
    try:
        _auth(request).api_keys.revoke(key_id)
    except AgentError as exc:
        # Last-admin protection (and any other refusal) surfaces as 400.
        status = 404 if exc.category is ErrorCategory.NOT_FOUND else 400
        raise HTTPException(status_code=status, detail=exc.message) from exc
    return {"revoked": key_id}


# ── signed-in users (GH-163) ──


@router.get("/admin/api/oauth/identities", dependencies=[Depends(require_admin)])
async def list_oauth_identities(request: Request) -> dict[str, Any]:
    identities = request.app.state.oauth.list_identities()
    return {"identities": identities, "count": len(identities)}


@router.delete("/admin/api/oauth/identities/{user}", dependencies=[Depends(require_admin)])
async def revoke_oauth_identity(user: str, request: Request) -> dict[str, Any]:
    revoked = request.app.state.oauth.revoke_user(user)
    flows = getattr(request.app.state, "idp_flows", None)
    if flows is not None:
        flows.drop_user(user)
    safe_user = sanitize_text(user, max_len=256)
    logger.warning("oauth user revoked by admin user=%s families=%d", safe_user, revoked)
    return {"user": safe_user, "revoked": revoked}


# ── overview ──


async def _adapter_health(adapter: SourceAdapter) -> bool:
    try:
        return bool(
            await asyncio.wait_for(adapter.health_check(), timeout=_HEALTH_CHECK_TIMEOUT)
        )
    except Exception:  # noqa: BLE001 — health is a boolean, never a crash
        return False


def _task_stats(task_store: Any) -> dict[str, Any]:
    """Best-effort stats; InMemoryTaskStore internals are duck-typed so a
    custom TaskStore without them degrades to nulls."""
    records = getattr(task_store, "_records", None)
    if records is None:
        return {"count": None, "interrupted": None}
    try:
        interrupted = sum(1 for r in records.values() if getattr(r, "interrupted", False))
        return {"count": len(records), "interrupted": interrupted}
    except Exception:  # noqa: BLE001
        return {"count": None, "interrupted": None}


@router.get("/admin/api/overview", dependencies=[Depends(require_admin)])
async def overview(request: Request) -> dict[str, Any]:
    """Settings summary (never secrets), adapter health, task-store stats,
    rate-limit config (§7 Overview row)."""
    settings = request.app.state.settings
    auth = _auth(request)
    adapters = list(_adapters(request).values())
    health = await asyncio.gather(*(_adapter_health(a) for a in adapters))
    return {
        "agent": {
            # RT-002: admin diagnostics intentionally surface the operator's
            # literal configured AGENT_NAME (not the normalized display_name) so
            # an unset/placeholder value is visible here for debugging. Protocol
            # surfaces (agent card, MCP serverInfo, /health) use display_name.
            "name": settings.agent_name,
            "description": settings.agent_description,
            "version": settings.agent_version,
            "base_url": settings.resolved_base_url,
            "dev_mode": settings.dev_mode,
        },
        "model": {
            "bedrock_region": settings.bedrock_region,
            "bedrock_model_arn": settings.bedrock_model_arn,
        },
        "adapters": [
            {
                "source_name": adapter.source_name,
                "allowed_hosts": list(adapter.allowed_hosts),
                "healthy": healthy,
            }
            for adapter, healthy in zip(adapters, health)
        ],
        "tasks": _task_stats(request.app.state.task_store),
        "rate_limits": {
            "per_identity_per_minute": settings.rate_limit_per_minute,
            "per_ip_unauth_per_minute": settings.unauth_rate_limit_per_minute,
        },
        "keys": {"count": auth.api_keys.count()},
        "bootstrap_armed": auth.bootstrap.armed,
        # GH-119 follow-up: reflect the resolved allow-list guard_origin()/
        # CorsMiddleware actually enforce (includes the deployment's own
        # resolved-base-URL origin), not just the raw configured list.
        "cors_origins": sorted(request.app.state.cors_origins),
    }


# ── credentials ──


def _field_summary(
    store: CredentialStore, namespace: str, field: CredentialField
) -> dict[str, Any]:
    return {
        "name": field.name,
        "label": field.label,
        "secret": field.secret,
        "required": field.required,
        "type": field.type,
        "help_text": field.help_text,
        # presence only — values never leave the store via this API
        "set": store.get(namespace, field.name) is not None,
    }


def _resolve_credential_field(
    request: Request, source: str, field_name: str
) -> tuple[str, CredentialField]:
    """Map (source, field) to a declared CredentialField or raise. Reserved
    namespaces other than Bedrock and __model__ are never reachable (§6)."""
    if source == NS_BEDROCK:
        for field in _BEDROCK_FIELDS:
            if field.name == field_name:
                return NS_BEDROCK, field
        raise HTTPException(status_code=404, detail="unknown Bedrock credential field")
    if source == NS_MODEL:
        for field in _MODEL_FIELDS:
            if field.name == field_name:
                return NS_MODEL, field
        raise HTTPException(status_code=404, detail="unknown model backend credential field")
    if source == NS_OAUTH_IDP:
        for field in _OAUTH_IDP_FIELDS:
            if field.name == field_name:
                return NS_OAUTH_IDP, field
        raise HTTPException(status_code=404, detail="unknown IdP credential field")
    if source in RESERVED_NAMESPACES:
        raise HTTPException(status_code=400, detail="reserved namespace")
    for adapter in _adapters(request).values():
        if adapter.source_name != source:
            continue
        for field in _declared_fields(request, adapter):
            if field.name == field_name:
                return source, field
        raise HTTPException(status_code=404, detail="unknown credential field")
    raise HTTPException(status_code=404, detail="unknown source")


@router.get("/admin/api/credentials", dependencies=[Depends(require_admin)])
async def list_credentials(request: Request) -> dict[str, Any]:
    store = _credential_store(request)
    sources = [
        {
            "source_name": adapter.source_name,
            "fields": [
                _field_summary(store, adapter.source_name, field)
                for field in _declared_fields(request, adapter)
            ],
        }
        for adapter in _adapters(request).values()
    ]
    return {
        "sources": sources,
        "model": {
            "source_name": NS_MODEL,
            "fields": [_field_summary(store, NS_MODEL, f) for f in _MODEL_FIELDS],
        },
        "oauth_idp": {
            "source_name": NS_OAUTH_IDP,
            "fields": [_field_summary(store, NS_OAUTH_IDP, f) for f in _OAUTH_IDP_FIELDS],
        },
        "bedrock": {
            "source_name": NS_BEDROCK,
            "fields": [_field_summary(store, NS_BEDROCK, f) for f in _BEDROCK_FIELDS],
        },
    }


@router.put(
    "/admin/api/credentials/{source}/{field_name}",
    dependencies=[Depends(require_admin)],
)
async def set_credential(
    source: str, field_name: str, body: CredentialValue, request: Request
) -> dict[str, Any]:
    namespace, field = _resolve_credential_field(request, source, field_name)
    value = body.value.strip()
    if not value:
        raise HTTPException(status_code=400, detail="value must not be empty")
    if field.type == "url":
        try:
            # getaddrinfo blocks — keep it off the event loop
            value = await asyncio.to_thread(validate_credential_url, value)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    _credential_store(request).set(namespace, field.name, value)
    logger.info("credential set: %s/%s", namespace, field.name)
    return {"source": source, "field": field.name, "set": True}


@router.delete(
    "/admin/api/credentials/{source}/{field_name}",
    dependencies=[Depends(require_admin)],
)
async def delete_credential(source: str, field_name: str, request: Request) -> dict[str, Any]:
    namespace, field = _resolve_credential_field(request, source, field_name)
    _credential_store(request).delete(namespace, field.name)
    logger.info("credential deleted: %s/%s", namespace, field.name)
    return {"source": source, "field": field.name, "set": False}


# ── tools ──


@router.get("/admin/api/tools", dependencies=[Depends(require_admin)])
async def list_tools(request: Request) -> dict[str, Any]:
    registry = request.app.state.registry
    return {
        "tools": [
            {
                "name": entry.name,
                "tier": entry.tier,
                "description": entry.description,
                "input_schema": entry.input_schema(),
                "sample": entry.decl.sample,
            }
            for entry in registry.all()
        ]
    }


def _safe_result(result: Any) -> Any:
    """Serialize a tool result without leaking non-JSON-able internals."""
    wire = getattr(result, "wire", None)
    if callable(wire):  # ContentModel — ship the renderable wire value
        payload: dict[str, Any] = {"value": wire()}
        data_type = getattr(type(result), "data_type", None)
        if data_type:
            payload["data_type"] = data_type
        to_text = getattr(result, "to_plain_text", None)
        if callable(to_text):
            payload["text"] = to_text()
        return payload
    if isinstance(result, BaseModel):
        return result.model_dump(mode="json")
    return jsonable_encoder(result)


@router.post("/admin/api/tools/{name}/try", dependencies=[Depends(require_admin)])
async def try_tool(
    name: str,
    request: Request,
    arguments: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Direct entry.invoke (admin only). Tool failures return safe error
    shapes (AgentError.public(); validation errors stripped of inputs)."""
    registry = request.app.state.registry
    entry = registry.get(name)
    if entry is None:
        raise HTTPException(status_code=404, detail="unknown tool")
    timeout = _TRY_TIMEOUTS.get(entry.tier, _TRY_TIMEOUTS[2])
    try:
        # RT-001/LRN-116: dispatch through the shared ToolEntry.invoke_any()
        # helper (registry.py) rather than re-implementing the is_generator
        # branch here — it also resolves a long_running=True coroutine
        # tool's DeferredResult inline under the same timeout deadline,
        # mirroring routes/mcp.py, instead of leaking the raw DeferredResult
        # (and its unawaited handle coroutine) to _safe_result().
        result = await entry.invoke_any(arguments, _adapters(request), timeout=timeout)
    except AgentError as exc:
        return {"ok": False, "error": exc.public()}
    except ToolInputValidationError as exc:
        # RT-004: raised ONLY by ToolEntry.invoke/invoke_gen's narrow
        # model_validate try — never by the tool body — so this IS an
        # input-shape defect, unlike a bare ValidationError (falls to the
        # generic Exception branch below instead of being mislabeled as
        # "validation").
        # SI-2: never build the error from raw Pydantic ``e['msg']`` —
        # ``include_input=False`` strips only ``input``, NOT ``msg``, and a
        # custom ``@field_validator`` that interpolates the rejected value
        # (e.g. ``raise ValueError(f'bad token {v!r}')``) surfaces that value
        # in ``msg``.  Route through the same SI-2-safe helper the MCP sibling
        # surface uses (routes/mcp.py), which keeps only loc + type.
        # GH-135: this discriminator is raised ONLY by the input-model
        # coercion step, never by the tool body, so a body-raised
        # ValidationError falls through to the generic except-Exception
        # branch below instead of being misreported as caller input here.
        return {
            "ok": False,
            "error": {
                "category": "validation",
                "message": safe_validation_message(
                    name, exc.validation_error, entry.decl.input_model
                ),
            },
        }
    except TimeoutError:
        return {
            "ok": False,
            "error": {"category": "timeout", "message": f"tool exceeded {timeout:.0f}s"},
        }
    except Exception as exc:  # noqa: BLE001 — internals stay out of the response
        # SI-2/RT-011: a body-raised ValidationError's __str__ embeds the raw
        # rejected value (`input_value=...`) — same for any other exception
        # whose message interpolates caller/tool-derived data. `logger.exception`
        # would format that message (and traceback) straight into the log, so
        # we never log exc's message. RT-004: log the exception TYPE plus
        # frame_locations() (common/redact.py, SI-2-safe: filename/lineno
        # only, never `.line`) — mirroring routes/mcp.py's identical catch-all
        # branch (RT-010) and every agent/loop.py dispatch site, all backed
        # by the same helper so this parity claim holds (LRN-044).
        frames = frame_locations(exc)
        logger.error(
            "tool try failed name=%s error_type=%s frames=%s",
            name,
            type(exc).__name__,
            frames,
        )
        return {
            "ok": False,
            "error": {"category": "internal", "message": "tool raised an unexpected error"},
        }
    return {"ok": True, "result": _safe_result(result)}


# ── self-check info ──


@router.get("/admin/api/selfcheck-info", dependencies=[Depends(require_admin)])
async def selfcheck_info(request: Request) -> dict[str, Any]:
    """Base URLs + endpoint list the selfcheck JS probes (§7 Self-check)."""
    settings = request.app.state.settings
    return {
        # RT-002: self-check intentionally shows the operator's literal configured
        # AGENT_NAME (not display_name) so an unset/placeholder value surfaces in
        # the admin console probe for debugging. Protocol surfaces use display_name.
        "agent": settings.agent_name,
        "version": settings.agent_version,
        "base_url": settings.resolved_base_url,
        "a2a_protocol_version": "0.3.0",
        "mcp_protocol_version": "2025-06-18",
        # GH-119 follow-up: reflect the resolved allow-list guard_origin()/
        # CorsMiddleware actually enforce (includes the deployment's own
        # resolved-base-URL origin), not just the raw configured list.
        "cors_origins": sorted(request.app.state.cors_origins),
        "endpoints": {
            "agent_card": "/.well-known/agent-card.json",
            "a2a_send": "/v1/message:send",
            "a2a_stream": "/v1/message:stream",
            "a2a_task": "/v1/tasks/{id}",
            "agui_run": "/ag-ui/run",
            "mcp": "/mcp",
            "prm": "/.well-known/oauth-protected-resource",
            "prm_suffixed": "/.well-known/oauth-protected-resource/mcp",
            "as_metadata": "/.well-known/oauth-authorization-server",
            "oauth_register": "/oauth/register",
            "oauth_authorize": "/oauth/authorize",
            "oauth_token": "/oauth/token",
            "health": "/health",
        },
    }
