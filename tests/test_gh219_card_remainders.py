"""GH-219 remainders: blank-description boot warning, card drops outputSchema.

Ruling: https://github.com/wailuen/a2a-sdk/issues/219#issuecomment-6345507008
"""

from __future__ import annotations

import gc
import json
import logging
from pathlib import Path

from agent_sdk import BaseAgentSettings
from agent_sdk.example.agent import make_agent
from agent_sdk.testing import FakeModelClient


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _build(tmp_path, **env):
    """Build the app and return the records ``agent_sdk.app`` emitted.

    A private handler (not ``caplog.handler``) counts each emission exactly
    once: caplog's handler also sits on the root logger, so attaching it to
    ``agent_sdk.app`` double-counts whenever an earlier test has left that
    logger propagating to root."""
    settings = BaseAgentSettings(
        DEV_MODE=True, DATA_DIR=str(tmp_path / "data"), AGENT_NAME="test-agent", **env
    )
    logger = logging.getLogger("agent_sdk.app")
    handler = _ListHandler()
    logger.addHandler(handler)
    try:
        app = make_agent(settings, model_client=FakeModelClient()).build_app()
    finally:
        logger.removeHandler(handler)
    app.state.credential_store.close()
    gc.collect()
    return handler.records


def _description_warnings(records):
    return [r for r in records if "AGENT_DESCRIPTION" in r.getMessage()]


def test_blank_description_warns_once(tmp_path):
    records = _build(tmp_path, AGENT_DESCRIPTION="   ")
    assert len(_description_warnings(records)) == 1


def test_set_description_does_not_warn(tmp_path):
    records = _build(tmp_path, AGENT_DESCRIPTION="Prices and briefings.")
    assert _description_warnings(records) == []


async def test_blank_description_still_falls_back_to_display_name(client):
    card = (await client.get("/.well-known/agent-card.json")).json()
    assert card["description"]


async def test_card_skills_omit_output_schema_but_keep_input_schema(client):
    text = (await client.get("/.well-known/agent-card.json")).text
    assert "outputSchema" not in text
    card = json.loads(text)
    assert card["skills"]
    for skill in card["skills"]:
        assert "inputSchema" in skill["x-sdk"]


async def test_card_bytes_no_longer_carry_output_schemas(client):
    card_bytes = len((await client.get("/.well-known/agent-card.json")).content)
    registry = client.app.state.registry
    dropped = sum(
        len(json.dumps(e.output_schema()))
        for e in registry.all()
        if e.output_schema() is not None
    )
    assert dropped > 0
    assert b"outputSchema" not in (await client.get("/.well-known/agent-card.json")).content
    assert card_bytes > 0


def test_docs_tools_example_shows_tags():
    docs = (Path(__file__).parent.parent / "docs" / "tools.md").read_text()
    assert "tags=" in docs.split("Rules the decorator enforces")[0]
