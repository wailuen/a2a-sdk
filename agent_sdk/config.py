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
    agent_name: str = Field(default="agent", alias="AGENT_NAME")
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
    max_turns: int = Field(default=20, alias="AGENT_SDK_MAX_TURNS")

    @field_validator("cors_origins")
    @classmethod
    def _no_wildcard_cors(cls, v: list[str]) -> list[str]:
        if "*" in v:
            raise ValueError("CORS_ORIGINS must be an explicit list, never '*'")
        return v

    @model_validator(mode="after")
    def _deployment_invariants(self) -> "BaseAgentSettings":
        # Best-effort guard; the template's `--workers 1` is the real control.
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
            if not self.master_key:
                raise ValueError("MASTER_KEY is required in production (DEV_MODE=false)")
            if len(self.master_key.get_secret_value()) < 32:
                raise ValueError(
                    "MASTER_KEY must be at least 32 characters and randomly generated "
                    "(the template and /new-agent generate it; never invent one)."
                )
        return self

    @property
    def resolved_base_url(self) -> str:
        """The advertised base URL: PUBLIC_URL, or the dev localhost fallback.

        Never empty — the agent card's REQUIRED ``url`` and the x-agui
        endpoint both derive from this (DESIGN.md §4.5).
        """
        if self.public_url:
            return self.public_url.rstrip("/")
        return f"http://localhost:{self.port}"
