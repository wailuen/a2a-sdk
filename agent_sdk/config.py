"""BaseAgentSettings — pydantic-settings base every agent subclasses.

Validation rules per DESIGN.md §4.4/§6. SDK-owned settings use the reserved
``AGENT_SDK_`` env prefix where noted; the classic operational vars
(PUBLIC_URL, MASTER_KEY, PORT, DEV_MODE, BEDROCK_*) keep their bare names
for parity with the reference agents.
"""

from __future__ import annotations

from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}

PLACEHOLDER_AGENT_NAME = "agent"


def _is_local(url: str) -> bool:
    try:
        return (urlparse(url).hostname or "") in _LOCAL_HOSTS
    except ValueError:
        return False


class BaseAgentSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ── identity ──
    agent_name: str = Field(default=PLACEHOLDER_AGENT_NAME, alias="AGENT_NAME")
    agent_description: str = Field(default="", alias="AGENT_DESCRIPTION")
    agent_version: str = Field(default="0.1.0", alias="AGENT_VERSION")

    # ── runtime ──
    port: int = Field(default=8000, alias="PORT")
    dev_mode: bool = Field(default=False, alias="DEV_MODE")
    public_url: str | None = Field(default=None, alias="PUBLIC_URL")
    web_concurrency: int = Field(default=1, alias="WEB_CONCURRENCY")
    data_dir: str = Field(default="./data", alias="DATA_DIR")

    # ── secrets / stores ──
    # MASTER_KEY encrypts the credential store (AES-256-GCM). It is NOT an
    # API key for any upstream service. Upstream/vendor API keys are stored IN
    # the credential store and accessed via self.credential("field") in adapters.
    master_key: SecretStr | None = Field(default=None, alias="MASTER_KEY")

    # ── Bedrock (default model backend) ──
    # Authenticates via EC2/ECS IAM role — no API key required.
    bedrock_region: str = Field(default="us-east-1", alias="BEDROCK_REGION")
    bedrock_model_arn: str | None = Field(default=None, alias="BEDROCK_MODEL_ARN")

    # ── OpenAI / Azure OpenAI model backend (alternative to Bedrock) ──
    # Non-secret operational vars only — the API key is NEVER in .env.
    # Seed it once via /admin → Model Backend (stored in the encrypted credential
    # store under the __model__ namespace). The SDK reads it from there at boot.
    openai_model: str | None = Field(default=None, alias="OPENAI_MODEL")
    openai_base_url: str | None = Field(default=None, alias="OPENAI_BASE_URL")
    azure_openai_endpoint: str | None = Field(default=None, alias="AZURE_OPENAI_ENDPOINT")
    azure_api_version: str | None = Field(default=None, alias="AZURE_API_VERSION")
    azure_openai_deployment: str | None = Field(default=None, alias="AZURE_OPENAI_DEPLOYMENT")

    # ── Azure Storage ──
    # Use EITHER connection_string (shared-key / SAS) OR account_name (managed
    # identity / workload identity). Setting both is an ambiguous-auth error.
    # connection_string is SecretStr so pydantic never serialises it into
    # repr/logs (SI-6).
    azure_storage_connection_string: SecretStr | None = Field(
        default=None, alias="AZURE_STORAGE_CONNECTION_STRING"
    )
    azure_storage_account_name: str | None = Field(
        default=None, alias="AZURE_STORAGE_ACCOUNT_NAME"
    )
    azure_storage_table_prefix: str = Field(
        default="agent", alias="AZURE_STORAGE_TABLE_PREFIX"
    )

    # ── CORS: explicit list, never wildcard ──
    cors_origins: list[str] = Field(
        default_factory=lambda: ["https://claude.ai"], alias="CORS_ORIGINS"
    )

    # ── SDK-reserved namespace ──
    trusted_proxies: list[str] = Field(
        default_factory=list, alias="AGENT_SDK_TRUSTED_PROXIES"
    )
    interrupt_ttl_seconds: int = Field(default=1800, alias="AGENT_SDK_INTERRUPT_TTL")
    max_interrupted_tasks: int = Field(default=100, alias="AGENT_SDK_MAX_INTERRUPTED")
    task_ttl_seconds: int = Field(default=3600, alias="AGENT_SDK_TASK_TTL")
    task_deadline_seconds: int = Field(default=600, alias="AGENT_SDK_TASK_DEADLINE")
    task_token_budget: int = Field(default=200_000, alias="AGENT_SDK_TASK_TOKEN_BUDGET")
    rate_limit_per_minute: int = Field(default=100, alias="AGENT_SDK_RATE_LIMIT")
    unauth_rate_limit_per_minute: int = Field(
        default=30, alias="AGENT_SDK_UNAUTH_RATE_LIMIT"
    )
    # One-time org consent (GH-136). OFF by default: every authorization is
    # gated on an admin API key. When ON, a client that an admin has ALREADY
    # approved re-authorizes silently — the operator consents once at setup
    # and the org's users connect without an admin key.
    #
    # Enable only when the agent's URL is not publicly discoverable: consent
    # is bound to the DCR *registration*, not to a person, so everyone who
    # reaches the server through that registration inherits the approval.
    # A never-approved client still hits the admin gate, and codes are still
    # only ever delivered to the client's registered redirect_uri.
    oauth_one_time_consent: bool = Field(
        default=False, alias="AGENT_SDK_OAUTH_ONE_TIME_CONSENT"
    )
    max_turns: int = Field(default=20, alias="AGENT_SDK_MAX_TURNS")
    max_output_tokens: int = Field(default=8192, alias="AGENT_SDK_MAX_OUTPUT_TOKENS")

    # ── A2UI component allow-list (SC-D2) ──
    # None (default) = all registered component types are available.
    # A non-None list restricts the catalog to only the named component types.
    # Types not in the list will raise an error if used as an emits= target.
    a2ui_allowed_components: list[str] | None = Field(
        default=None, alias="AGENT_SDK_A2UI_ALLOWED_COMPONENTS"
    )

    @field_validator("cors_origins")
    @classmethod
    def _no_wildcard_cors(cls, v: list[str]) -> list[str]:
        if "*" in v:
            raise ValueError("CORS_ORIGINS must be an explicit list, never '*'")
        return v

    @model_validator(mode="after")
    def _deployment_invariants(self) -> "BaseAgentSettings":
        # Best-effort guard; the template's `--workers 1` is the real control.
        # With Azure Table Storage backends for credential/commitment/subscription
        # stores, multi-replica deployments are supported; WEB_CONCURRENCY > 1
        # remains unsupported within a single process (uvicorn worker model).
        # Use Azure Container Apps replicas instead.
        if self.web_concurrency > 1:
            raise ValueError(
                "WEB_CONCURRENCY > 1 is unsupported: the task store, SSE queues and "
                "rate limiter are process-local (DESIGN.md §2). Run one process."
            )
        if self.dev_mode and self.public_url and not _is_local(self.public_url):
            raise ValueError(
                "DEV_MODE=true with a non-localhost PUBLIC_URL is refused: dev mode "
                "relaxes security checks that must never face the network."
            )
        if not self.dev_mode:
            if not self.public_url:
                raise ValueError("PUBLIC_URL is required in production (DEV_MODE=false)")
            if not self.public_url.startswith("https://") and not _is_local(self.public_url):
                parsed = urlparse(self.public_url)
                raise ValueError(
                    f"PUBLIC_URL must use https:// in production (got: {parsed.scheme}). "
                    "Set DEV_MODE=true to bypass."
                )
            if not self.master_key:
                raise ValueError("MASTER_KEY is required in production (DEV_MODE=false)")
            if len(self.master_key.get_secret_value()) < 32:
                raise ValueError(
                    "MASTER_KEY must be at least 32 characters and randomly generated "
                    "(the template and /new-agent generate it; never invent one)."
                )
        if (
            self.azure_storage_connection_string is not None
            and self.azure_storage_account_name is not None
        ):
            raise ValueError(
                "AZURE_STORAGE_CONNECTION_STRING and AZURE_STORAGE_ACCOUNT_NAME are "
                "mutually exclusive (ambiguous auth): set one or the other, not both."
            )
        return self

    @property
    def is_placeholder_name(self) -> bool:
        """True when agent_name is the placeholder default or blank/whitespace.

        Single source of truth for the placeholder-or-blank predicate used by
        ``_check_agent_name`` (app boot), ``display_name`` (identity surfaces),
        and ``build_agent_card`` (A2A agent card).  Centralised here so the
        three call-sites cannot drift back to inconsistent implementations.

        **Reserved name (RT-007)**: the literal string ``"agent"``
        (case-insensitive, with or without surrounding whitespace) is
        permanently reserved as the unset-placeholder sentinel.  There is no
        escape hatch: an operator who sets ``AGENT_NAME=agent`` explicitly
        receives the same normalization and warning / production ``ValueError``
        as if the variable were absent.  Choose any other name (e.g.
        ``"my-agent"``) to avoid this treatment.
        """
        name = self.agent_name.strip()
        return not name or name.lower() == PLACEHOLDER_AGENT_NAME

    @property
    def display_name(self) -> str:
        """Normalized agent name for all identity-bearing protocol surfaces.

        Returns the configured ``agent_name`` unchanged when it is a real name.
        When ``agent_name`` is the placeholder default (``"agent"``, matched
        case-insensitively) or blank — possible in DEV_MODE, blocked by
        ``build_app()``'s ``ValueError`` in production — returns the neutral
        sentinel ``"agent-sdk-agent"`` so that no protocol surface (MCP
        serverInfo, health, agent card) ever advertises the raw placeholder.
        Apply this everywhere instead of ``agent_name`` directly: MCP
        serverInfo.name/title, the health ``agent`` field, and the agent card
        ``name`` (``build_agent_card``) — the REQUIRED A2A identity surface,
        which must be normalized alongside the others (RT-001).

        See ``is_placeholder_name`` for the reserved-name limitation (RT-007).
        """
        if self.is_placeholder_name:
            return "agent-sdk-agent"
        return self.agent_name.strip()

    @property
    def resolved_base_url(self) -> str:
        """The advertised base URL: PUBLIC_URL, or the dev localhost fallback.

        Never empty — the agent card's REQUIRED ``url`` and the x-agui
        endpoint both derive from this (DESIGN.md §4.5).
        """
        if self.public_url:
            return self.public_url.rstrip("/")
        return f"http://localhost:{self.port}"
