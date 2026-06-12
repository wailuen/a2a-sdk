"""Settings for {{AGENT_NAME}} — extend BaseAgentSettings, add domain knobs.

A factory (not an import-time instance) so tests can construct isolated
settings. The ``AGENT_SDK_`` env prefix is reserved by the SDK.
"""

from __future__ import annotations

from agent_sdk import BaseAgentSettings


class Settings(BaseAgentSettings):
    # Add domain settings here, e.g.:
    # sample_api_base_url: str = Field(
    #     default="https://api.example.com", alias="SAMPLE_API_BASE_URL"
    # )
    pass


def make_settings() -> Settings:
    return Settings()
