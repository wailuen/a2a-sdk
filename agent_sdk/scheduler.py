"""Stub module to produce a helpful error for common mis-imports.

There is no ``agent_sdk.scheduler`` module. Use::

    from agent_sdk.contrib import Scheduler

See ``agent_sdk/contrib/scheduler.py`` for full documentation.
"""

raise ImportError(
    "agent_sdk.scheduler does not exist. "
    "Use: from agent_sdk.contrib import Scheduler"
)
