"""AlphaGeo agent assembly (DESIGN §4.1 shape).

``make_agent`` is a factory so tests can inject a ``FakeModelClient`` and
isolated settings without triggering app construction at import; ``main.py`` is
the thin uvicorn entrypoint.
"""

from __future__ import annotations

from pathlib import Path

from agent_sdk import Agent, CredentialField
from agent_sdk.agent.model_client import ModelClient

from .config import Settings, make_model_client, make_settings
from .persona import PERSONA
from .sources.alphageo import AlphaGeoSource
from .tools import climate


def make_agent(
    settings: Settings | None = None,
    *,
    model_client: ModelClient | None = None,
) -> Agent:
    settings = settings or make_settings()
    agent = Agent(
        settings=settings,
        persona=PERSONA,
        skills_dir=Path(__file__).parent / "skills",
        toolsets=[climate.tools],
        model_client=model_client or make_model_client(settings),
    )
    agent.register_source(
        AlphaGeoSource,
        credentials=[
            CredentialField(name="api_key", label="AlphaGeo API key", secret=True),
        ],
    )
    return agent
