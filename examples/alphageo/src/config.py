"""Settings + model-client factory for the AlphaGeo agent.

Extends ``BaseAgentSettings`` with the AlphaGeo base URL and the OpenAI/Azure
model knobs (this example runs on the OpenAI ModelClient seam, not Bedrock).
The vendor AlphaGeo API key is NOT a setting — it is resolved per call from the
encrypted credential store or the forwarded ``X-Agent-Credentials`` header.

Secrets stay ``SecretStr`` and are only ever read inside the factory; they are
never logged or echoed.
"""

from __future__ import annotations

from pydantic import Field, SecretStr

from agent_sdk import BaseAgentSettings
from agent_sdk.agent.openai_client import OpenAIModelClient

DEFAULT_BASE_URL = "https://app.alphageo.ai/api/public/v1"


class Settings(BaseAgentSettings):
    # AlphaGeo upstream (the vendor key is per-call, never stored here).
    alphageo_base_url: str = Field(default=DEFAULT_BASE_URL, alias="ALPHAGEO_BASE_URL")

    # OpenAI (vanilla)
    openai_api_key: SecretStr | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-5", alias="OPENAI_MODEL")
    openai_base_url: str | None = Field(default=None, alias="OPENAI_BASE_URL")

    # Azure OpenAI (takes precedence when endpoint + key are both set)
    azure_openai_endpoint: str | None = Field(default=None, alias="AZURE_OPENAI_ENDPOINT")
    azure_openai_key: SecretStr | None = Field(default=None, alias="AZURE_OPENAI_KEY")
    azure_openai_api_version: str = Field(default="2024-10-21", alias="AZURE_OPENAI_API_VERSION")
    azure_openai_deployment: str = Field(default="mcp-alphageo", alias="AZURE_OPENAI_DEPLOYMENT")

    # Reasoning-model knobs (gpt-5). Leave the token cap unset by default — a
    # small cap would be consumed by reasoning and yield an empty completion.
    openai_reasoning_effort: str | None = Field(default=None, alias="OPENAI_REASONING_EFFORT")
    openai_max_completion_tokens: int | None = Field(
        default=None, alias="OPENAI_MAX_COMPLETION_TOKENS"
    )


def make_settings() -> Settings:
    return Settings()


def make_model_client(settings: Settings) -> OpenAIModelClient:
    """Pick Azure when fully configured, else vanilla OpenAI. Raises a config
    error (no secret in the message) when neither provider is set up."""
    if settings.azure_openai_endpoint and settings.azure_openai_key:
        return OpenAIModelClient(
            model=settings.azure_openai_deployment,
            api_key=settings.azure_openai_key.get_secret_value(),
            azure_endpoint=settings.azure_openai_endpoint,
            azure_api_version=settings.azure_openai_api_version,
            azure_deployment=settings.azure_openai_deployment,
            reasoning_effort=settings.openai_reasoning_effort,
            max_completion_tokens=settings.openai_max_completion_tokens,
        )
    if settings.openai_api_key:
        return OpenAIModelClient(
            model=settings.openai_model,
            api_key=settings.openai_api_key.get_secret_value(),
            base_url=settings.openai_base_url,
            reasoning_effort=settings.openai_reasoning_effort,
            max_completion_tokens=settings.openai_max_completion_tokens,
        )
    raise ValueError(
        "No model provider configured: set OPENAI_API_KEY, or both "
        "AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_KEY."
    )
