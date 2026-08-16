"""RT-013 (medium): ``ToolInputValidationError`` is the migration target the
CHANGELOG's GH-135 entry prescribes to every downstream consumer ("must
switch to catching ``ToolInputValidationError``"), so it must be reachable
from the stable public surface (``agent_sdk``) rather than only the private
``agent_sdk.agent.registry`` module path.
"""

import agent_sdk
from agent_sdk.agent.registry import (
    ToolInputValidationError as _RegistryToolInputValidationError,
)


def test_tool_input_validation_error_importable_from_top_level() -> None:
    assert agent_sdk.ToolInputValidationError is _RegistryToolInputValidationError


def test_tool_input_validation_error_in_all() -> None:
    assert "ToolInputValidationError" in agent_sdk.__all__
