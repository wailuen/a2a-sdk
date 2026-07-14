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
import inspect
import logging
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
from .credentials.store import NS_BEDROCK, NS_MODEL, CredentialStore, resolver_for_source, validate_namespace
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

logger = logging.getLogger(__name__)


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
        exclude_from_catalog: list[str] | None = None,
        toolsets: list[ToolSet] | None = None,
        model_client: ModelClient | None = None,
        task_store: TaskStore | None = None,
        console_static_dir: Path | None = None,
        lifespan_extras: list[Callable[[FastAPI], Any]] | None = None,
    ) -> None:
        """Assemble an agent from its parts.

        Args:
            settings: A ``BaseAgentSettings`` (or subclass) instance.
            persona: System-prompt string.  Exactly one of ``persona`` or
                ``artifacts_dir`` is required.
            artifacts_dir: Directory containing Jinja2 artifact files
                (``system.md``, …).  Mutually exclusive with ``persona``.
            artifact_vars: Extra variables rendered into artifact templates.
            skills_dir: Directory of ``SKILL.md`` files added to the system
                prompt's skill catalog.
            exclude_from_catalog: Names of skills (from ``skills_dir``) to
                omit from the advertised catalog text folded into the
                system prompt, while keeping them fully invocable —
                ``app.state.skills.load(name)`` (and the ``load_skill``
                tool) still succeeds for an excluded name; it is simply not
                listed. Validated at ``build_app()``: every name must
                correspond to a discoverable skill, else raises
                ``ValueError``.

                This is the recommended pattern for always-on/guardrail
                skills: inline the skill's content directly into
                ``persona``/``artifacts_dir`` so it is unconditionally
                present in the system prompt (never dependent on the model
                choosing to call ``load_skill``), and list that same
                skill's name here so its now-redundant catalog entry is
                suppressed rather than duplicating instructions the model
                already always sees.
            toolsets: ``ToolSet`` instances whose tools are registered.
            model_client: Override the auto-configured ``ModelClient``
                (useful in tests and for non-Bedrock backends).
            task_store: Override the default ``InMemoryTaskStore``.
            console_static_dir: Agent-provided static assets that shadow the
                built-in console files (DESIGN.md §10.3).
            lifespan_extras: Additional ASGI lifespan context managers run
                inside the app's lifespan, after source adapters are
                initialised and before the sweeper task.  Each callable
                receives the ``FastAPI`` app and must return an async context
                manager (i.e. be decorated with ``@asynccontextmanager``).

                This is the **blessed pattern** for background tasks and
                long-lived resources that need ``app.state`` access at
                startup.  The SDK itself uses it for
                ``contrib.commitments.commitments_lifespan`` and
                ``contrib.webhooks.webhooks_renewal_lifespan``.

                Minimal example — a periodic heartbeat task::

                    from contextlib import asynccontextmanager
                    import asyncio
                    from fastapi import FastAPI

                    # Capture asyncio.sleep at import time so test patches
                    # of asyncio.sleep don't affect the background task.
                    _sleep = asyncio.sleep

                    @asynccontextmanager
                    async def heartbeat_lifespan(app: FastAPI):
                        async def _beat():
                            while True:
                                await _sleep(60)
                                print("alive")
                        task = asyncio.create_task(_beat())
                        try:
                            yield
                        finally:
                            task.cancel()

                    agent = Agent(
                        ...,
                        lifespan_extras=[heartbeat_lifespan],
                    )

                Use ``from agent_sdk.contrib import Scheduler`` for
                background jobs; see ``agent_sdk/contrib/scheduler.py``
                for usage.  Note: ``agent_sdk.scheduler`` is a stub that
                raises ``ImportError`` on import; use
                ``from agent_sdk.contrib import Scheduler`` instead.
        """
        if persona is None and artifacts_dir is None:
            raise ValueError("Agent requires either persona= or artifacts_dir=")
        if persona is not None and artifacts_dir is not None:
            raise ValueError(
                "Agent requires exactly one of persona= or artifacts_dir=, not both"
            )
        if persona is not None and not persona.strip():
            raise ValueError("Agent persona= must not be empty or whitespace-only")
        self.settings = settings
        self.persona = persona
        self.artifacts_dir = artifacts_dir
        self.artifact_vars = artifact_vars or {}
        self.skills_dir = skills_dir
        self.exclude_from_catalog = list(exclude_from_catalog or [])
        self.toolsets = list(toolsets or [])
        self._model_client = model_client
        self._task_store = task_store
        self.console_static_dir = console_static_dir
        self._lifespan_extras = list(lifespan_extras or [])
        self._sources: dict[type[SourceAdapter], _SourceRegistration] = {}
        self._sync_reply: Callable[[Any], str | None] | None = None

    def set_sync_reply(self, fn: Callable[[Any], str | None]) -> None:
        """Register a hook called before task creation in message/send.

        The hook receives the incoming Message object and returns a plain-text
        reply string or None. If a non-empty string is returned the route skips
        task creation and returns a bare Message immediately (A2A v0.3.0 §2
        quick-response pattern). If None is returned (or no hook is registered)
        the normal Task path is taken.
        """
        self._sync_reply = fn

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

    def _validate_emits(
        self,
        registry: ToolRegistry,
        allowed_components: list[str] | None = None,
    ) -> None:
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
                # SC-D2: check against allowed_components allowlist when set.
                if allowed_components is not None and emits.component not in allowed_components:
                    raise ValueError(
                        f"tool {entry.name!r} emits {emits.__name__!r} (component "
                        f"{emits.component!r}), which is not in the agent's "
                        f"a2ui_allowed_components list {allowed_components!r}"
                    )
            elif not (isinstance(emits, type) and issubclass(emits, BaseModel)):
                raise ValueError(
                    f"tool {entry.name!r}: emits must be a ContentModel or pydantic "
                    "BaseModel subclass"
                )
            # ── SC-F1: enforce return annotation matches emits ────────────────
            # Resolve string annotations (from __future__ import annotations) using
            # inspect.get_annotations with eval=True so we get real types.
            fn = entry.decl.fn
            _annotation_resolved = True
            try:
                resolved = inspect.get_annotations(fn, eval_str=True)
            except Exception:
                resolved = getattr(fn, "__annotations__", {})
                _annotation_resolved = False
            ret = resolved.get("return")
            # Accept: no annotation (None), typing.Any, exact emits type, or a
            # superclass of emits.  Reject any other concrete type.
            #
            # RT-002: inspect.get_annotations collapses `-> None` and a missing
            # return annotation to the same Python None.  Check __annotations__
            # to distinguish: only skip when the key is genuinely absent.
            if ret is None:
                raw = getattr(fn, "__annotations__", {})
                if "return" not in raw:
                    continue  # unannotated — permitted
                # explicit `-> None` with a non-None emits is a clear mismatch;
                # fall through to the ValueError below
            # SI-4: if the annotation could not be eval'd (e.g. NameError for a
            # type imported only inside a fixture/closure), ret may be a raw
            # string.  We cannot validate it — log a warning and skip rather
            # than raising a false-positive ValueError that aborts build_app().
            if isinstance(ret, str):
                if _annotation_resolved:
                    logger.warning(
                        "_validate_emits: annotation for %r resolved to string %r"
                        " — skipping SC-F1 check",
                        fn.__name__,
                        ret,
                    )
                else:
                    logger.warning(
                        "_validate_emits: could not resolve annotation %r for %r"
                        " — skipping SC-F1 check",
                        ret,
                        fn.__name__,
                    )
                continue
            import typing as _typing
            if ret is _typing.Any:
                continue  # -> Any — permitted
            if inspect.isclass(ret) and issubclass(emits, ret):
                continue  # emits is ret or a subclass of ret — permitted
            # Guard against generic non-Union origins (e.g. list[T], tuple[T],
            # set[T]).  typing.get_args(list[KpiCard]) returns (KpiCard,) —
            # identical to what Optional[KpiCard] produces — so without this
            # check the Union unwrap path below would silently pass list[T].
            # Any annotation with a concrete __origin__ that is not Union is
            # an immediate mismatch (SC-F1 false-positive fix, RT-SC-F1-LIST).
            #
            # GH-91: Before the generic-origin rejection, handle async-generator
            # return annotations.  For is_generator tools the honest annotation
            # is AsyncIterator[T] or AsyncGenerator[T, None]; both have a non-Union
            # __origin__, so without this branch they fall into the ValueError below.
            import collections.abc as _abc
            _origin = getattr(ret, "__origin__", None)
            if entry.decl.is_generator and _origin in (
                _abc.AsyncIterator,
                _abc.AsyncGenerator,
            ):
                _gen_args = _typing.get_args(ret)
                # AsyncIterator[T] → args=(T,); AsyncGenerator[T, None] → args=(T, None).
                # In both forms the yield type is the first argument.
                yield_type = _gen_args[0] if _gen_args else None
                if yield_type is None or yield_type is _typing.Any:
                    continue  # unannotated yield type or Any — permitted
                # Validate yield_type against emits using the same rule as coroutines:
                # emits must be yield_type itself or a subclass of it.
                if inspect.isclass(yield_type) and issubclass(emits, yield_type):
                    continue  # emits satisfies the yield type — permitted
                raise ValueError(
                    f"tool {fn.__name__!r} async-generator return annotation {ret!r} "
                    f"yields {yield_type!r} but emits={emits!r} — "
                    f"the yield type must be a superclass of (or equal to) emits"
                )
            if _origin is not None and _origin is not _typing.Union:
                raise ValueError(
                    f"tool {fn.__name__!r} return annotation {ret!r} does not match "
                    f"emits={emits!r}"
                )
            # Handle Optional[T] / Union[T, None]: unwrap, filter out NoneType,
            # and accept if every remaining arg is a class that emits satisfies.
            _union_args = [
                a for a in _typing.get_args(ret) if a is not type(None)
            ]
            if _union_args and all(
                inspect.isclass(a) and issubclass(emits, a)
                for a in _union_args
            ):
                continue  # Optional[emits] or Union[emits, ...] — permitted
            raise ValueError(
                f"tool {fn.__name__!r} return annotation {ret!r} does not match "
                f"emits={emits!r}"
            )

    def _build_model_client(self, credential_store: CredentialStore) -> ModelClient:
        if self._model_client is not None:
            return self._model_client
        s = self.settings
        # OpenAI / Azure OpenAI backend: non-secret vars in .env; API key from store.
        if s.openai_model or s.azure_openai_endpoint:
            try:
                import openai as _openai_pkg  # noqa: F401
            except ModuleNotFoundError:
                raise ImportError(
                    "openai package is required for the OpenAI/Azure OpenAI backend — "
                    "install it with: pip install 'agent-sdk[openai]'"
                ) from None
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
            bearer_token=credential_store.get(NS_BEDROCK, "bearer_token"),
            aws_access_key_id=credential_store.get(NS_BEDROCK, "aws_access_key_id"),
            aws_secret_access_key=credential_store.get(NS_BEDROCK, "aws_secret_access_key"),
            aws_session_token=credential_store.get(NS_BEDROCK, "aws_session_token"),
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

            if self.settings.dev_mode:
                import logging as _logging
                _logging.getLogger(__name__).warning(
                    "Credential store: AZURE_STORAGE_ACCOUNT_NAME is set but "
                    "AZURE_STORAGE_CONNECTION_STRING is absent. In dev, this requires "
                    "`az login` (DefaultAzureCredential). Use Azurite instead: "
                    "set AZURE_STORAGE_CONNECTION_STRING=UseDevelopmentStorage=true "
                    "and start Azurite (`azurite --silent --location /tmp/azurite`)."
                )
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

    def _check_agent_name(self) -> None:
        name = self.settings.agent_name
        if not self.settings.is_placeholder_name:
            return
        is_blank = not name.strip()
        if is_blank:
            dev_msg = (
                "AGENT_NAME is empty or whitespace — set AGENT_NAME in the "
                "environment to a meaningful identifier before deploying"
            )
            exc_msg = (
                "AGENT_NAME is empty or whitespace. "
                "Set AGENT_NAME in the environment before running in production."
            )
        else:
            dev_msg = (
                "AGENT_NAME is unset or set to the reserved placeholder %r — set "
                "AGENT_NAME in the environment to a meaningful identifier before "
                "deploying (note: 'agent' is a reserved placeholder name; choose "
                "any other name)"
            )
            exc_msg = (
                f"AGENT_NAME is unset or set to the reserved placeholder {name!r}. "
                "Set AGENT_NAME in the environment before running in production. "
                "Note: 'agent' is a reserved placeholder name; choose any other name."
            )
        if self.settings.dev_mode:
            if is_blank:
                logger.warning(dev_msg)
            else:
                logger.warning(dev_msg, name)
        else:
            raise ValueError(exc_msg)

    def build_app(self) -> FastAPI:
        settings = self.settings
        base_url = settings.resolved_base_url

        configure_logging()
        self._check_agent_name()

        registry = ToolRegistry(self.toolsets, dict(self._sources))
        allowed_components = settings.a2ui_allowed_components
        self._validate_emits(registry, allowed_components=allowed_components)

        for entry in registry.all():
            if not entry.decl.tags:
                logger.warning(
                    "Skill '%s' has empty tags — it will not be discoverable by tag in A2A catalogs.",
                    entry.name,
                )

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
            bare_prm_url=f"{base_url}/.well-known/oauth-protected-resource",
            identity_limiter=RateLimiter(settings.rate_limit_per_minute),
            unauth_limiter=RateLimiter(settings.unauth_rate_limit_per_minute),
        )

        task_store = self._task_store or InMemoryTaskStore(
            task_ttl=settings.task_ttl_seconds,
            interrupt_ttl=settings.interrupt_ttl_seconds,
            max_interrupted=settings.max_interrupted_tasks,
        )
        skills = SkillsRegistry(self.skills_dir)
        if self.exclude_from_catalog:
            unknown = [n for n in self.exclude_from_catalog if n not in skills.skills]
            if unknown:
                raise ValueError(
                    "exclude_from_catalog references skill(s) not found in "
                    f"skills_dir: {', '.join(unknown)}"
                )
        model_client = self._build_model_client(credential_store)
        policies = LoopPolicies(
            max_turns=settings.max_turns,
            deadline_seconds=float(settings.task_deadline_seconds),
            token_budget=settings.task_token_budget,
            max_output_tokens=settings.max_output_tokens,
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
        catalog = skills.catalog_text(exclude=self.exclude_from_catalog)
        if catalog:
            system_prompt = f"{system_prompt}\n\n{catalog}"

        from .a2ui.catalog import get_system_prompt_section

        a2ui_section = get_system_prompt_section(allowed_components)
        if a2ui_section:
            system_prompt = system_prompt + "\n\n" + a2ui_section

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
                try:
                    await sweep_task
                except asyncio.CancelledError:
                    pass
                # Cancel all live workers, close resume channels, and
                # sentinel-close SSE subscriber queues before adapters are
                # torn down (DESIGN.md §5.2 shutdown contract).
                task_store.close_all()
                for adapter in adapters.values():
                    try:
                        await adapter.aclose()
                    except Exception:
                        logger.warning("adapter.aclose failed", exc_info=True)
                shutdown = getattr(model_client, "shutdown", None)
                if callable(shutdown):
                    try:
                        shutdown()
                    except Exception:
                        logger.warning("model_client.shutdown failed", exc_info=True)
                try:
                    credential_store.close()
                except Exception:
                    logger.warning("credential_store.close failed", exc_info=True)

        app_title = settings.display_name
        app = FastAPI(
            title=app_title,
            version=settings.agent_version,
            lifespan=lifespan,
        )
        app.middleware("http")(request_id_middleware)
        # RTGA-007: strip trailing slashes so the defense-in-depth origin guards
        # in MCP routes match the same normalized form that CorsMiddleware stores
        # internally.  Without this, CORS_ORIGINS=['https://app.example.com/']
        # would pass the middleware check but 403 the MCP route guards.
        _cors_origins = {o.rstrip("/") for o in settings.cors_origins} | {"https://claude.ai"}
        app.add_middleware(CorsMiddleware, origins=_cors_origins)
        app.state.cors_origins = _cors_origins

        # A2A surface (/v1/*) speaks the spec error envelope, including for
        # auth failures. FastAPI's default emits {"detail": ...}; translate
        # all HTTP errors there to {"error": {code, message}} per A2A §5.1.
        # The HTTP status is authoritative; -32000 is the JSON-RPC
        # implementation-defined server-error slot, never colliding with
        # A2A's -3200x codes. Non-/v1/ paths fall through to FastAPI default.
        from fastapi.exception_handlers import (
            http_exception_handler,
            request_validation_exception_handler,
        )
        from fastapi.exceptions import RequestValidationError as _RequestValidationError
        from fastapi.responses import JSONResponse as _JSONResponse
        from starlette.exceptions import HTTPException as _StarletteHTTPException

        # 404 → -32601 (Method not found): application routes explicitly call
        # a2a_error(A2A_TASK_NOT_FOUND) when a task is missing, so a bare 404
        # HTTPException here is always an unknown-route dispatch miss, never a
        # task lookup miss. -32601 is the standard JSON-RPC code for exactly
        # that and is already used identically for MCP method-dispatch misses
        # (the `_METHOD_NOT_FOUND` fallback in routes/mcp.py `_dispatch`).
        # This supersedes the w021/RT-003 ruling
        # (2026-06-19), which left 404 unmapped so it fell through to the
        # generic -32603 default without considering -32601.
        # 405 → -32004 (UnsupportedOperation): "method not allowed" is
        # semantically an unsupported operation on that resource. The forward
        # A2A_HTTP_STATUS maps -32004 → 501 for capability-absent cases; the
        # asymmetry is intentional (HTTP method mismatch ≠ missing capability).
        _A2A_CODE: dict[int, int] = {
            401: -32000, 403: -32000,
            404: -32601, 405: -32004, 415: -32005,
        }

        @app.exception_handler(_StarletteHTTPException)
        async def _a2a_auth_envelope(request: Any, exc: _StarletteHTTPException) -> Any:
            if request.url.path.startswith("/v1/"):
                code = _A2A_CODE.get(exc.status_code, -32603)
                return _JSONResponse(
                    status_code=exc.status_code,
                    content={"error": {"code": code, "message": str(exc.detail)}},
                    headers=getattr(exc, "headers", None) or None,
                )
            return await http_exception_handler(request, exc)

        @app.exception_handler(_RequestValidationError)
        async def _a2a_validation_envelope(request: Any, exc: _RequestValidationError) -> Any:
            if request.url.path.startswith("/v1/"):
                # Report offending field LOCATIONS only — never echo submitted
                # values (SI-2: secrets hygiene). e.g. "body.historyLength".
                fields = ", ".join(
                    ".".join(str(loc) for loc in e["loc"]) for e in exc.errors()[:3]
                )
                detail = f"invalid params (check: {fields})" if fields else "invalid params"
                return _JSONResponse(
                    status_code=400,
                    content={"error": {"code": -32602, "message": detail}},
                )
            return await request_validation_exception_handler(request, exc)

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
            settings, registry, app.state.credential_fields,
            allowed_components=allowed_components,
        )
        app.state.default_capabilities = A2uiCapabilities()
        app.state.console_static_dirs = []
        app.state.sync_reply = self._sync_reply  # SC-A1: bare-Message hook

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
