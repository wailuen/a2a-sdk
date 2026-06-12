"""Identity, API keys, OAuth token store, route dependencies.

Team routes mounted after ``build_app()`` add
``Depends(agent_sdk.auth.require_identity)`` themselves (DESIGN.md §10.3).
"""

from .identity import Identity
from .middleware import (
    require_admin,
    require_api_key_identity,
    require_identity,
    resolve_identity,
)

__all__ = [
    "Identity",
    "require_admin",
    "require_api_key_identity",
    "require_identity",
    "resolve_identity",
]
