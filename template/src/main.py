"""{{AGENT_NAME}} — assembly. This is the whole file (DESIGN §4.1 shape)."""

from pathlib import Path

from agent_sdk import Agent, CredentialField

from .config import make_settings
from .persona import PERSONA
from .sources.sample_api import SampleApiAdapter
from .tools import widgets

agent = Agent(
    settings=make_settings(),
    persona=PERSONA,
    skills_dir=Path(__file__).parent / "skills",
    toolsets=[widgets.tools],
)
agent.register_source(
    SampleApiAdapter,
    credentials=[
        CredentialField(name="api_token", label="Sample API token", secret=True),
    ],
)
app = agent.build_app()
