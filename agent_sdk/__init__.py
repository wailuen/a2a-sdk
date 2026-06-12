"""agent-sdk — build A2A / AG-UI / A2UI agents with an OAuth-protected MCP
surface from domain code only (DESIGN.md §1).

Stable core exports (strict SemVer — DESIGN.md §4.0). Everything else is
importable from its submodule; ``agent_sdk.testing`` and ``agent_sdk.contrib``
are provisional.
"""

from .agent.loop import LoopPolicies, ToolInterrupt
from .agent.model_client import ModelClient, ModelResponse, ModelToolCall
from .agent.registry import ToolSet
from .app import Agent
from .config import BaseAgentSettings
from .credentials.fields import CredentialField
from .models.errors import AgentError, ErrorCategory
from .sources import SourceAdapter

__version__ = "0.1.0"

__all__ = [
    "Agent",
    "AgentError",
    "BaseAgentSettings",
    "CredentialField",
    "ErrorCategory",
    "LoopPolicies",
    "ModelClient",
    "ModelResponse",
    "ModelToolCall",
    "SourceAdapter",
    "ToolInterrupt",
    "ToolSet",
    "__version__",
]
