"""obo — MSAL on-behalf-of token exchange (DESIGN.md §9).

EXPERIMENTAL (DESIGN.md §4.0): provisional until the m365 port validates it; may
change in minor releases with a CHANGELOG notice. Ships as the ``obo`` extra
(``pip install agent-sdk[obo]``) — ``msal`` is imported lazily so this package
imports without it.

Three cooperating pieces, mapping to the DESIGN §9 contract:

- **assertion extraction / threading** — :class:`OboAssertionMiddleware` binds the
  inbound JWT Bearer into a request-scoped contextvar; the detached agent worker
  inherits it; a source reads it via :func:`current_assertion`.
- **token exchange (cached, 30s buffer)** — :class:`OboExchanger` wraps an MSAL
  confidential-client app; MSAL caches the access token, the buffer refuses an
  assertion within 30 s of its own expiry so the worker doesn't mint a token
  that dies mid-flight.
- **persistent token cache** — :class:`MsalTokenCache` backs MSAL's
  ``SerializableTokenCache`` against the SDK encrypted credential store so
  access/refresh tokens survive restarts. Created automatically by
  ``GraphSource`` when ``build_app()`` calls ``_bind_credential_store``.
- **auth-context threading to adapters** — :class:`GraphSource` (a SourceAdapter)
  exchanges at tool time and calls host-pinned Graph with the delegated bearer.

Plus :mod:`.scopes` Graph scope helpers.

Wiring (the integrator owns this; the m365 port is the first consumer)::

    from agent_sdk.contrib.obo import (
        GraphSource, GRAPH_CREDENTIAL_FIELDS, OboAssertionMiddleware,
    )
    from agent_sdk.contrib.obo.scopes import graph_scopes

    agent.register_source(
        GraphSource,
        credentials=GRAPH_CREDENTIAL_FIELDS,
        init_kwargs={"scopes": graph_scopes("User.Read", "Mail.Read")},
    )
    app = agent.build_app()
    app.add_middleware(OboAssertionMiddleware)   # before startup

**Deployment constraint:** OBO requires the inbound Bearer to be an Entra-issued
user assertion whose audience is this agent's app registration. The SDK does not
enforce that (its own auth accepts API keys / SDK-issued OAuth tokens); the front
door must present an Entra token, or the exchange fails closed at MSAL. See
:mod:`.context`.

**Secrets hygiene:** assertions and minted tokens are never logged or returned in
errors; MSAL error descriptions are scrubbed of JWT fragments before they can
reach an error detail.
"""

from __future__ import annotations

from .cache import MsalTokenCache
from .context import (
    OboAssertionMiddleware,
    bind_assertion,
    current_assertion,
    looks_like_assertion,
    unbind_assertion,
)
from .exchange import OboCredentials, OboExchanger, OboToken, TokenExpiredError
from .scopes import (
    DEFAULT_READ_SCOPES,
    GRAPH_API_V1,
    GRAPH_BASE,
    graph_scope,
    graph_scopes,
)
from .source import GRAPH_CREDENTIAL_FIELDS, GraphSource

__all__ = [
    # cache
    "MsalTokenCache",
    # exchange
    "OboExchanger",
    "OboCredentials",
    "OboToken",
    "TokenExpiredError",
    # context / threading
    "OboAssertionMiddleware",
    "bind_assertion",
    "unbind_assertion",
    "current_assertion",
    "looks_like_assertion",
    # source
    "GraphSource",
    "GRAPH_CREDENTIAL_FIELDS",
    # scopes
    "graph_scope",
    "graph_scopes",
    "GRAPH_BASE",
    "GRAPH_API_V1",
    "DEFAULT_READ_SCOPES",
]
