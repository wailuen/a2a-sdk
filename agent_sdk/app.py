"""Agent builder → FastAPI app factory (DESIGN.md §4.1).

Explicit registration, no import side effects: toolsets and sources are
collected on the ``Agent`` and resolved by ``build_app()``, where every
mis-wiring fails loudly at boot, never at call time.

``build_app()`` returns a plain FastAPI app; mounting team routes after
build is supported — but SDK auth is per-route dependencies, so team routes
are unauthenticated until they add ``Depends(agent_sdk.auth.require_identity)``.
"""

from __future__ import annotations

import asyncio
from asyncio import sleep as _asyncio_sleep
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Callable

from fastapi import FastAPI
from pydantic import BaseModel

from .a2ui.translator import A2uiCapabilities
from .agent.bedrock import BedrockModelClient
from .agent.loop import LoopPolicies
from .agent.model_client import ModelClient
from .agent.registry import ToolRegistry, ToolSet
from .agent.skills import SkillsRegistry
from .auth.api_keys import ApiKeyStore, BootstrapManager
from .auth.middleware import AuthRuntime
from .auth.oauth_tokens import OAuthTokenStore
from .common.cors import CorsMiddleware
from .common.limits import RateLimiter
from .config import BaseAgentSettings
from .credentials.fields import CredentialField
from .credentials.store import NS_MODEL, CredentialStore, resolver_for_source, validate_namespace
from .credentials.encrypted_sqlite import EncryptedSqliteStore
from .models.content_types import ContentModel, content_type_for
from .observability import configure_logging, request_id_middleware
from .routes.agent_card import build_agent_card
from .sources import SourceAdapter
from .tasks.memory import InMemoryTaskStore
from .tasks.store import TaskStore

# Dev-mode only: a stable key so local data survives restarts without
# forcing MASTER_KEY ceremony. Production requires a real MASTER_KEY (§4.4).
_DEV_MASTER_KEY = "agent-sdk-dev-mode-master-key-do-not-use-in-production"

_SWEEP_INTERVAL_SECONDS = 60.0


@dataclass(slots=True)
class _SourceRegistration:
    adapter_cls: type[SourceAdapter]
    credentials: list[CredentialField] = field(default_factory=list)
    init_kwargs: dict[str, Any] = field(default_factory=dict)


class Agent:
    """Assembles settings + persona + skills + toolsets + sources into an app."""

    def __init__(
        self,
        *,
        settings: BaseAgentSettings,
        persona: str | None = None,
        artifacts_dir: Path | None = None,
        artifact_vars: dict[str, Any] | None = None,
        skills_dir: Path | None = None,
        toolsets: list[ToolSet] | None = None,
        model_client: ModelClient | None = None,
        task_store: TaskStore | None = None,
        console_static_dir: Path | None = None,
        lifespan_extras: list[Callable[[FastAPI], Any]] | None = None,
    ) -> None:
        if persona is None and artifacts_dir is None:
            raise ValueError("Agent requires either persona= or artifacts_dir=")
        self.settings = settings
        self.persona = persona
        self.artifacts_dir = artifacts_dir
        self.artifact_vars = artifact_vars or {}
        self.skills_dir = skills_dir
        self.toolsets = list(toolsets or [])
        self._model_client = model_client
        self._task_store = task_store
        self.console_static_dir = console_static_dir
        self._lifespan_extras = list(lifespan_extras or [])
        self._sources: dict[type[SourceAdapter], _SourceRegistration] = {}

    def register_source(
        self,
        adapter_cls: type[SourceAdapter],
        *,
        credentials: list[CredentialField] | None = None,
        init_kwargs: dict[str, Any] | None = None,
    ) -> None:
        """Once per class; ``source_name`` is read from the adapter class."""
        if adapter_cls in self._sources:
            raise ValueError(f"{adapter_cls.__name__} is already registered")
        if not adapter_cls.source_name:
            raise ValueError(f"{adapter_cls.__name__} must declare source_name")
        validate_namespace(adapter_cls.source_name)
        for reg in self._sources.values():
            if reg.adapter_cls.source_name == adapter_cls.source_name:
                raise ValueError(
                    f"duplicate source_name {adapter_cls.source_name!r} "
                    f"({reg.adapter_cls.__name__} vs {adapter_cls.__name__})"
                )
        self._sources[adapter_cls] = _SourceRegistration(
            adapter_cls=adapter_cls,
            credentials=list(credentials or []),
            init_kwargs=dict(init_kwargs or {}),
        )

    # ── build ──

    def _validate_emits(self, registry: ToolRegistry) -> None:
        for entry in registry.all():
            emits = entry.decl.emits
            if emits is None:
                continue
            if issubclass(emits, ContentModel):
                if content_type_for(emits.data_type) is not emits:
                    raise ValueError(
                        f"tool {entry.name!r} emits {emits.__name__}, which is not a "
                        "registered Profile/domain content type "
                        "(register_content_type it first)"
                    )
            elif not (isinstance(emits, type) and issubclass(emits, BaseModel)):
                raise ValueError(
                    f"tool {entry.name!r}: emits must be a ContentModel or pydantic "
                    "BaseModel subclass"
                )

    def _build_model_client(self, credential_store: CredentialStore) -> ModelClient:
        if self._model_client is not None:
            return self._model_client
        s = self.settings
        # OpenAI / Azure OpenAI backend: non-secret vars in .env; API key from store.
        if s.openai_model or s.azure_openai_endpoint:
            from .agent.openai_client import OpenAIModelClient

            api_key = (
                credential_store.get(NS_MODEL, "openai_api_key")
                or credential_store.get(NS_MODEL, "azure_openai_api_key")
            )
            return OpenAIModelClient(
                model=s.openai_model or "",
                api_key=api_key,  # None when not yet seeded — fails at first LLM call
                base_url=s.openai_base_url,
                azure_endpoint=s.azure_openai_endpoint,
                azure_api_version=s.azure_api_version,
                azure_deployment=s.azure_openai_deployment,
            )
        # Default: Bedrock (IAM — no API key)
        if not s.bedrock_model_arn:
            raise ValueError(
                "No model backend configured. Set BEDROCK_MODEL_ARN for Bedrock (IAM), "
                "or OPENAI_MODEL / AZURE_OPENAI_ENDPOINT for OpenAI "
                "(then seed the API key once via /admin → Model Backend)."
            )
        return BedrockModelClient(
            region=s.bedrock_region,
            model_arn=s.bedrock_model_arn,
        )

    def _build_credential_store(self) -> CredentialStore:
        master_key = (
            self.settings.master_key.get_secret_value()
            if self.settings.master_key
            else _DEV_MASTER_KEY
        )
        if self.settings.azure_storage_connection_string is not None:
            from .credentials.azure_table import AzureTableCredentialStore

            return AzureTableCredentialStore(
                master_key,
                connection_string=self.settings.azure_storage_connection_string.get_secret_value(),
                prefix=self.settings.azure_storage_table_prefix,
            )
        if self.settings.azure_storage_account_name is not None:
            from .credentials.azure_table import AzureTableCredentialStore

            return AzureTableCredentialStore(
                master_key,
                account_name=self.settings.azure_storage_account_name,
                prefix=self.settings.azure_storage_table_prefix,
            )
        if not self.settings.dev_mode:
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "Credential store: falling back to local SQLite (%s/credentials.db). "
                "Set AZURE_STORAGE_CONNECTION_STRING (or AZURE_STORAGE_ACCOUNT_NAME) "
                "to use Azure Table Storage as the primary store. "
                "Run `python3 -m agent_sdk migrate-store` to lift existing credentials.",
                self.settings.data_dir,
            )
        db_path = Path(self.settings.data_dir) / "credentials.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return EncryptedSqliteStore(db_path, master_key)

    def build_app(self) -> FastAPI:
        settings = self.settings
        base_url = settings.resolved_base_url

        registry = ToolRegistry(self.toolsets, dict(self._sources))
        self._validate_emits(registry)

        credential_store = self._build_credential_store()
        api_keys = ApiKeyStore(credential_store)
        bootstrap = BootstrapManager(api_keys)
        oauth_store = OAuthTokenStore(
            credential_store,
            issuer=base_url,
            canonical_resource=f"{base_url}/mcp",
        )
        auth = AuthRuntime(
            api_keys=api_keys,
            bootstrap=bootstrap,
            oauth=oauth_store,
            trusted_proxies=list(settings.trusted_proxies),
            prm_url=f"{base_url}/.well-known/oauth-protected-resource/mcp",
            identity_limiter=RateLimiter(settings.rate_limit_per_minute),
            unauth_limiter=RateLimiter(settings.unauth_rate_limit_per_minute),
        )

        task_store = self._task_store or InMemoryTaskStore(
            task_ttl=settings.task_ttl_seconds,
            interrupt_ttl=settings.interrupt_ttl_seconds,
            max_interrupted=settings.max_interrupted_tasks,
        )
        skills = SkillsRegistry(self.skills_dir)
        model_client = self._build_model_client(credential_store)
        policies = LoopPolicies(
            max_turns=settings.max_turns,
            deadline_seconds=float(settings.task_deadline_seconds),
            token_budget=settings.task_token_budget,
        )

        if self.artifacts_dir is not None:
            from .agent.artifacts import ArtifactLoader
            persona_str = ArtifactLoader(self.artifacts_dir).render(
                "system",
                agent_name=settings.agent_name,
                agent_version=settings.agent_version,
                **self.artifact_vars,
            )
        else:
            persona_str = self.persona  # type: ignore[assignment]

        system_prompt = persona_str.strip()
        catalog = skills.catalog_text()
        if catalog:
            system_prompt = f"{system_prompt}\n\n{catalog}"

        sources = dict(self._sources)
        lifespan_extras = list(self._lifespan_extras)

        @asynccontextmanager
        async def lifespan(app: FastAPI) -> AsyncIterator[None]:
            bootstrap.arm_if_needed()
            adapters: dict[type[SourceAdapter], SourceAdapter] = {}
            for cls, reg in sources.items():
                resolver = resolver_for_source(credential_store, cls.source_name)
                adapter = cls(settings, resolver, **reg.init_kwargs)
                adapter._bind_credential_store(credential_store)
                adapters[cls] = adapter
            app.state.adapters = adapters

            async def _sweeper() -> None:
                while True:
                    await _asyncio_sleep(_SWEEP_INTERVAL_SECONDS)
                    task_store.sweep()

            sweep_task = asyncio.create_task(_sweeper())
            try:
                async with AsyncExitStack() as stack:
                    for extra in lifespan_extras:
                        await stack.enter_async_context(extra(app))
                    yield
            finally:
                sweep_task.cancel()
                for adapter in adapters.values():
                    await adapter.aclose()
                shutdown = getattr(model_client, "shutdown", None)
                if callable(shutdown):
                    shutdown()
                credential_store.close()

        app = FastAPI(
            title=settings.agent_name,
            version=settings.agent_version,
            lifespan=lifespan,
        )
        configure_logging()
        app.middleware("http")(request_id_middleware)
        _cors_origins = set(settings.cors_origins) | {"https://claude.ai"}
        app.add_middleware(CorsMiddleware, origins=_cors_origins)

        # A2A surface (/v1/*) speaks the spec error envelope, including for
        # auth failures. FastAPI's default emits {"detail": ...}; translate
        # 401/403 there to {"error": {code, message}} while preserving the
        # HTTP status and challenge headers (WWW-Authenticate). The HTTP
        # status is authoritative; -32000 is the JSON-RPC implementation-
        # defined server-error slot, never colliding with A2A's -3200x.
        from fastapi.exception_handlers import http_exception_handler
        from fastapi.responses import JSONResponse as _JSONResponse
        from starlette.exceptions import HTTPException as _StarletteHTTPException

        @app.exception_handler(_StarletteHTTPException)
        async def _a2a_auth_envelope(request: Any, exc: _StarletteHTTPException) -> Any:
            if request.url.path.startswith("/v1/") and exc.status_code in (401, 403):
                return _JSONResponse(
                    status_code=exc.status_code,
                    content={"error": {"code": -32000, "message": str(exc.detail)}},
                    headers=getattr(exc, "headers", None) or None,
                )
            return await http_exception_handler(request, exc)

        # frozen app.state contract (consumed by routes + console + tests)
        app.state.settings = settings
        app.state.auth = auth
        app.state.registry = registry
        app.state.adapters = {}  # filled at lifespan startup
        app.state.credential_store = credential_store
        app.state.credential_fields = {
            reg.adapter_cls.source_name: reg.credentials for reg in sources.values()
        }
        app.state.task_store = task_store
        app.state.skills = skills
        app.state.model_client = model_client
        app.state.oauth = oauth_store
        app.state.loop_policies = policies
        app.state.persona = persona_str
        app.state.system_prompt = system_prompt
        app.state.agent_card = build_agent_card(
            settings, registry, app.state.credential_fields
        )
        app.state.default_capabilities = A2uiCapabilities()
        app.state.console_static_dirs = []

        # routers are imported here, not at module top, so a missing surface
        # is a loud boot failure local to build_app()
        from .routes import a2a as a2a_routes
        from .routes import ag_ui as ag_ui_routes
        from .routes import agent_card as card_routes
        from .routes import mcp as mcp_routes
        from .routes import oauth as oauth_routes

        app.include_router(card_routes.router)
        app.include_router(a2a_routes.router)
        app.include_router(ag_ui_routes.router)
        app.include_router(oauth_routes.router)  # root-mounted, no prefix
        app.include_router(mcp_routes.router)  # carries its own /mcp prefix

        self._mount_console(app)
        return app

    def _mount_console(self, app: FastAPI) -> None:
        """Admin console + health routes. admin.py serves the static assets
        itself with file-by-file shadowing across ``console_static_dirs``
        (agent override dir first, SDK assets last — §10.3)."""
        from .routes import admin as admin_routes
        from .routes import health as health_routes

        app.include_router(health_routes.router)
        app.include_router(admin_routes.router)

        dirs: list[Any] = []
        if self.console_static_dir is not None:
            dirs.append(self.console_static_dir)
        dirs.append(admin_routes.SDK_STATIC_DIR)
        app.state.console_static_dirs = dirs
