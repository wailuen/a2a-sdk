"""uvicorn entrypoint: ``uvicorn agent_sdk.example.main:app``."""

from .agent import make_agent

app = make_agent().build_app()
