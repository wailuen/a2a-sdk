"""A2UI v0.9.1 translator + catalog advertisement (DESIGN.md §5.4)."""

from .catalog import get_system_prompt_section
from .translator import A2uiCapabilities, translate

__all__ = ["A2uiCapabilities", "get_system_prompt_section", "translate"]
