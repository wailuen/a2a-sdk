"""Microsoft Graph delegated-permission scope helpers (DESIGN.md §9).

Generalized from the m365 reference agent. ``GRAPH_BASE`` is the fully-qualified
resource prefix Entra expects for delegated Graph scopes; a bare ``Mail.Read``
also works for v2 endpoints, but the fully-qualified form is unambiguous across
tenants and is what MSAL recommends for confidential-client OBO.

These are *convenience constants*, not policy: an agent grants only the scopes
it actually needs. Pass an explicit list to :class:`~agent_sdk.contrib.obo.GraphSource`
(or :class:`~agent_sdk.contrib.obo.OboExchanger`) — there is intentionally no
"all scopes" default that would over-request consent.
"""

from __future__ import annotations

GRAPH_BASE = "https://graph.microsoft.com/"

# Graph v1.0 API root. /beta is intentionally NOT offered — it is unversioned
# and unstable; an agent that needs it sets its own base URL explicitly.
GRAPH_API_V1 = "https://graph.microsoft.com/v1.0"


def graph_scope(name: str) -> str:
    """Fully-qualify a short Graph permission name (``"Mail.Read"`` →
    ``"https://graph.microsoft.com/Mail.Read"``). Idempotent: an already
    fully-qualified scope (or the OIDC ``offline_access``/``openid`` family,
    or a different resource URI) is returned unchanged."""
    if "://" in name or name in _OIDC_SCOPES:
        return name
    return f"{GRAPH_BASE}{name}"


def graph_scopes(*names: str) -> list[str]:
    """Build a fully-qualified scope list from short names (deduped, order-
    preserving). ``graph_scopes("Mail.Read", "Calendars.Read")``."""
    seen: dict[str, None] = {}
    for name in names:
        seen.setdefault(graph_scope(name), None)
    return list(seen)


# OIDC scopes are resource-less and must never be prefixed with the Graph host.
_OIDC_SCOPES = frozenset({"openid", "profile", "email", "offline_access"})

# A minimal, read-only default for examples/tests. Deliberately small — User.Read
# is the least-privilege "who am I" scope. NOT a recommended production set;
# request exactly what your tools call.
DEFAULT_READ_SCOPES: list[str] = graph_scopes("User.Read")

__all__ = [
    "GRAPH_BASE",
    "GRAPH_API_V1",
    "graph_scope",
    "graph_scopes",
    "DEFAULT_READ_SCOPES",
]
