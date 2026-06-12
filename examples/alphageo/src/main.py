"""uvicorn entrypoint: ``uvicorn src.main:app --port 8045 --workers 1``."""

from .agent import make_agent

app = make_agent().build_app()
