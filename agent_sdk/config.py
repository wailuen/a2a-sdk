"""BaseAgentSettings — pydantic-settings base every agent subclasses.

Validation rules per DESIGN.md §4.4/§6. SDK-owned settings use the reserved
``AGENT_SDK_`` env prefix where noted; the classic operational vars
(PUBLIC_URL, MASTER_KEY, PORT, DEV_MODE, BEDROCK_*) keep their bare names
for parity with the reference agents.
"""

from __future__ import annotations

import re
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, SecretStr, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}

PLACEHOLDER_AGENT_NAME = "agent"


_ENTRA_LOGIN_HOSTS = frozenset(
    {
        "login.microsoftonline.com",
        "login.microsoftonline.us",
        "login.partner.microsoftonline.cn",
        "login.windows.net",
        "sts.windows.net",
    }
)
_GUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_ISSUER_SETTING = "AGENT_SDK_OAUTH_IDP_ISSUER"
_CONSUMERS_TENANT_GUID = "9188040d-6c67-4c5b-b112-36a304b66dad"


def parse_idp_issuer(issuer: str) -> str | None:
    """Validate an OIDC issuer; return the Entra tenant GUID, or None for a non-Entra issuer.

    Raises ValueError (naming the setting, never echoing the value) for a non-https
    issuer, one with a query/fragment, or an Entra issuer that is not the
    single-tenant ``https://<login host>/<tenant GUID>/v2.0`` form.
    """
    try:
        parsed = urlparse(issuer)
        host = (parsed.hostname or "").lower()
    except ValueError:
        raise ValueError(f"{_ISSUER_SETTING} is not a valid URL") from None
    if parsed.scheme != "https" or not host:
        raise ValueError(f"{_ISSUER_SETTING} must be an https:// URL")
    if parsed.query or parsed.fragment or "?" in issuer or "#" in issuer:
        raise ValueError(f"{_ISSUER_SETTING} must not contain a query or fragment")
    if host not in _ENTRA_LOGIN_HOSTS:
        return None
    if host == "sts.windows.net":
        raise ValueError(
            f"{_ISSUER_SETTING} must be a v2.0 Entra issuer; the v1 sts.windows.net issuer is not supported"
        )
    segments = [seg for seg in parsed.path.split("/") if seg]
    if len(segments) != 2 or segments[1] != "v2.0" or parsed.path.endswith("/"):
        raise ValueError(
            f"{_ISSUER_SETTING} must be https://<login host>/<tenant GUID>/v2.0"
        )
    if not _GUID_RE.fullmatch(segments[0]) or segments[0].lower() == _CONSUMERS_TENANT_GUID:
        raise ValueError(
            f"{_ISSUER_SETTING} must name one tenant by GUID; "
            "common, organizations, consumers and domain names are not supported"
        )
    return segments[0].lower()


def _is_local(url: str) -> bool:
    try:
        return (urlparse(url).hostname or "") in _LOCAL_HOSTS
    except ValueError:
        return False


class BaseAgentSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
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
    # GH-133: forwarded verbatim to the underlying AsyncOpenAI/AsyncAzureOpenAI
    # constructor, which owns its own retry/backoff. Unset (None) leaves the
    # openai SDK's own defaults (max_retries=2) untouched.
    # RT-005: unlike OPENAI_MODEL/OPENAI_BASE_URL/AZURE_* above — bare names
    # kept for parity with the reference agents — these are new SDK settings,
    # so per DESIGN.md §4.0 they carry the reserved AGENT_SDK_ prefix.
    openai_max_retries: int | None = Field(
        default=None, alias="AGENT_SDK_OPENAI_MAX_RETRIES"
    )
    openai_timeout: float | None = Field(
        default=None, alias="AGENT_SDK_OPENAI_TIMEOUT"
    )
    # GH-155: OpenAIModelClient already accepts these; without settings an
    # env-configured agent could not reach them. ``reasoning_effort`` is sent
    # verbatim on every call (only set it for a reasoning deployment such as
    # gpt-5 / o-series); ``max_completion_tokens`` is the reasoning-inclusive
    # hard ceiling on every call, including the cap-exit summary call.
    openai_reasoning_effort: str | None = Field(
        default=None, alias="AGENT_SDK_OPENAI_REASONING_EFFORT"
    )
    openai_max_completion_tokens: int | None = Field(
        default=None, gt=0, alias="AGENT_SDK_OPENAI_MAX_COMPLETION_TOKENS"
    )

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
    inject_current_date: bool = Field(
        default=True, alias="AGENT_SDK_INJECT_CURRENT_DATE"
    )
    timezone: str = Field(default="UTC", alias="AGENT_SDK_TIMEZONE")
    interrupt_ttl_seconds: int = Field(default=1800, alias="AGENT_SDK_INTERRUPT_TTL")
    max_interrupted_tasks: int = Field(default=100, alias="AGENT_SDK_MAX_INTERRUPTED")
    task_ttl_seconds: int = Field(default=3600, alias="AGENT_SDK_TASK_TTL")
    task_deadline_seconds: int = Field(default=600, alias="AGENT_SDK_TASK_DEADLINE")
    task_token_budget: int = Field(default=200_000, alias="AGENT_SDK_TASK_TOKEN_BUDGET")
    rate_limit_per_minute: int = Field(default=100, alias="AGENT_SDK_RATE_LIMIT")
    unauth_rate_limit_per_minute: int = Field(
        default=30, alias="AGENT_SDK_UNAUTH_RATE_LIMIT"
    )
    # One-time consent (GH-136). OFF by default: every authorization is
    # gated on an admin API key. When ON, a client that an admin has ALREADY
    # approved re-authorizes silently.
    #
    # This is per-registration, not automatically per-org (GH-138): DCR
    # (``POST /oauth/register``) mints a fresh, unconsented ``client_id`` on
    # every registration call, so by default this only saves a RETURNING
    # client from re-hitting the gate — a brand-new user whose connector
    # performs its own DCR call still hits the admin gate the first time.
    # For genuine org-wide sharing (one pre-approved connection every org
    # member uses), run
    # ``python -m agent_sdk provision-org-oauth-client`` to mint one
    # ``client_id``, pre-approve it offline, and pin it into the connector
    # platform's static/pre-registered OAuth Client ID field — every user
    # who connects through that pinned registration then inherits the same
    # approval.
    #
    # Enable only when the agent's URL is not publicly discoverable: consent
    # is bound to the DCR *registration*, not to a person, so everyone who
    # reaches the server through an approved registration inherits it.
    # A never-approved client still hits the admin gate, and codes are still
    # only ever delivered to the client's registered redirect_uri.
    oauth_one_time_consent: bool = Field(
        default=False, alias="AGENT_SDK_OAUTH_ONE_TIME_CONSENT"
    )
    # ── IdP sign-in at /oauth/authorize (GH-152, ADR-003). Off by default. ──
    # The client secret is NOT a setting: it lives in the credential store
    # under __oauth_idp__/client_secret (SI-4, SI-6).
    oauth_idp: Literal["none", "oidc"] = Field(default="none", alias="AGENT_SDK_OAUTH_IDP")
    oauth_idp_issuer: str | None = Field(default=None, alias="AGENT_SDK_OAUTH_IDP_ISSUER")
    oauth_idp_client_id: str | None = Field(
        default=None, alias="AGENT_SDK_OAUTH_IDP_CLIENT_ID"
    )
    oauth_idp_required_role: str | None = Field(
        default=None, alias="AGENT_SDK_OAUTH_IDP_REQUIRED_ROLE"
    )
    oauth_idp_required_group: str | None = Field(
        default=None, alias="AGENT_SDK_OAUTH_IDP_REQUIRED_GROUP"
    )
    oauth_idp_session_hours: int = Field(
        default=720, ge=1, le=2160, alias="AGENT_SDK_OAUTH_IDP_SESSION_HOURS"
    )
    oauth_idp_disable_api_keys: bool = Field(
        default=False, alias="AGENT_SDK_OAUTH_IDP_DISABLE_API_KEYS"
    )
    oauth_idp_allow_all_issuer_users: bool = Field(
        default=False, alias="AGENT_SDK_OAUTH_IDP_ALLOW_ALL_ISSUER_USERS"
    )
    max_turns: int = Field(default=20, alias="AGENT_SDK_MAX_TURNS")
    final_summary: bool = Field(default=True, alias="AGENT_SDK_FINAL_SUMMARY")
    max_output_tokens: int = Field(default=8192, alias="AGENT_SDK_MAX_OUTPUT_TOKENS")
    final_summary_max_tokens: int = Field(
        default=1024, alias="AGENT_SDK_FINAL_SUMMARY_MAX_TOKENS"
    )

    # GH-168: replayed AG-UI history messages longer than this keep their start
    # and end with an omission marker. ge=1000 so the marker always fits.
    agui_max_message_chars: int = Field(
        default=32000, ge=1000, alias="AGENT_SDK_AGUI_MAX_MESSAGE_CHARS"
    )

    # RT-001 (GH-143 follow-up): routes/mcp.py's per-identity GET-stream cap
    # is keyed on Identity.subject, which is an OAuth client_id or API-key id
    # — a *registration*, never an end user (auth/oauth_tokens.py,
    # auth/api_keys.py). Org-wide OAuth client provisioning
    # (`provision-org-oauth-client`) and a shared API key both collapse every
    # caller in the org onto ONE identity key, so the default cap must admit
    # an entire organization's concurrent connectors. None (default) leaves
    # routes/mcp.py's own SDK default (see `_MAX_GET_STREAMS_PER_IDENTITY`);
    # an operator with a larger org can raise this without touching code.
    # RT-003 (round 5): `ge=1`, not a bare int. Both route guards read
    # `if owner_count >= limit:`, so a 0 or negative limit is unconditionally
    # true and denies EVERY stream for EVERY identity from the very first
    # request — with no startup error and no log. `0` is the natural operator
    # reading of "unlimited", which makes the silent failure mode the likely
    # one. Verified before the bound: `=0` yielded an effective cap of 0 and
    # `=-5` a cap of -5. Refuse at settings construction instead; "unlimited"
    # is expressed by leaving the variable unset.
    max_mcp_streams_per_identity: int | None = Field(
        default=None, ge=1, alias="AGENT_SDK_MAX_MCP_STREAMS_PER_IDENTITY"
    )

    # RT-001 (A2A stream admission cap follow-up): routes/a2a.py's per-identity
    # cap on concurrent open message:stream/tasks:subscribe connections is
    # keyed the same way as max_mcp_streams_per_identity above — see that
    # field's docstring for why org-wide provisioning modes need this
    # overridable. None (default) leaves routes/a2a.py's own SDK default (see
    # `_MAX_A2A_STREAMS_PER_IDENTITY`).
    # RT-003 (round 5): `ge=1` for the same reason as the MCP cap above.
    max_a2a_streams_per_identity: int | None = Field(
        default=None, ge=1, alias="AGENT_SDK_MAX_A2A_STREAMS_PER_IDENTITY"
    )

    # ── A2UI component allow-list (SC-D2) ──
    # None (default) = all registered component types are available.
    # A non-None list restricts the catalog to only the named component types.
    # Types not in the list will raise an error if used as an emits= target.
    a2ui_allowed_components: list[str] | None = Field(
        default=None, alias="AGENT_SDK_A2UI_ALLOWED_COMPONENTS"
    )

    @field_validator("timezone")
    @classmethod
    def _valid_timezone(cls, v: str, info: ValidationInfo) -> str:
        # GH-154: the zone is only used for the date line. With injection off
        # nothing loads it, so a host without zone data must still boot.
        if not info.data.get("inject_current_date", True):
            return v
        from zoneinfo import ZoneInfoNotFoundError

        from .common.tz import load_zone

        try:
            load_zone(v)
        except (ZoneInfoNotFoundError, ValueError, OSError):
            # Fixed text only: the operator's value is never echoed (SI-2).
            raise ValueError(
                "AGENT_SDK_TIMEZONE must be a valid IANA time zone name "
                "(e.g. 'UTC', 'Asia/Singapore'); if the name is valid, this "
                "host has no time zone data: install the 'tzdata' package"
            ) from None
        return v

    @field_validator("cors_origins")
    @classmethod
    def _no_wildcard_cors(cls, v: list[str]) -> list[str]:
        if "*" in v:
            raise ValueError("CORS_ORIGINS must be an explicit list, never '*'")
        return v

    @model_validator(mode="after")
    def _deployment_invariants(self) -> "BaseAgentSettings":
        # Best-effort guard; the template's `--workers 1` is the real control.
        # Azure Table Storage backends share credentials, commitments and
        # subscriptions across replicas, but IdP flows, consent tickets, auth
        # codes, access tokens, MCP sessions and the task store stay
        # per-process. With OAuth/IdP sign-in on, run exactly one replica
        # (GH-162). WEB_CONCURRENCY > 1 is unsupported within a process.
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
