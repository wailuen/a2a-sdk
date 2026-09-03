"""agent-sdk — build A2A / AG-UI / A2UI agents with an OAuth-protected MCP
surface from domain code only (DESIGN.md §1).

Stable core exports (strict SemVer — DESIGN.md §4.0). Everything else is
importable from its submodule; ``agent_sdk.testing`` and ``agent_sdk.contrib``
are provisional.
"""

from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    __version__: str = _pkg_version("agent-sdk")
except PackageNotFoundError:  # running from source tree without pip install
    __version__ = "0.0.0+dev"

from .agent.artifacts import ArtifactLoader
from .agent.deferred import DeferredResult
from .agent.loop import LoopPolicies, ToolInterrupt
from .agent.model_client import ModelClient, ModelResponse, ModelToolCall
from .agent.registry import ToolInputValidationError, ToolSet
from .agent.reuse import ReuseKind, Reusable
from .app import Agent
from .common.redact import safe_block_text, safe_cell_text, safe_error_text
from .config import BaseAgentSettings
from .credentials.fields import CredentialField
from .credentials.store import NS_MODEL
from .models.errors import AgentError, ErrorCategory
from .sources import SourceAdapter

__all__ = [
    "Agent",
    "AgentError",
    "ArtifactLoader",
    "BaseAgentSettings",
    "CredentialField",
    "DeferredResult",
    "NS_MODEL",
    "ErrorCategory",
    "LoopPolicies",
    "ModelClient",
    "ModelResponse",
    "ModelToolCall",
    "Reusable",
    "ReuseKind",
    "safe_block_text",
    "safe_cell_text",
    "safe_error_text",
    "SourceAdapter",
    "ToolInputValidationError",
    "ToolInterrupt",
    "ToolSet",
    "__version__",
]
