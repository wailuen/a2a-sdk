"""webhooks — inbound Microsoft Graph change-notification receiver (DESIGN §9).

EXPERIMENTAL (DESIGN §4.0): provisional until the m365 port validates it; may
change in minor releases with a CHANGELOG notice.

Graph webhooks are *unauthenticated inbound HTTP*: Graph POSTs a notification to
a public URL with no bearer token, and authenticity rests entirely on a
``clientState`` secret you set at subscription time and Graph echoes back. This
module is the hardened generalization of the m365 reference receiver, with the
five things that reference skeleton lacked:

1. **Constant-time, fail-closed ``clientState`` validation** (the reference used
   ``!=``) — :class:`WebhookDispatcher` compares with :func:`hmac.compare_digest`
   and, with no secret configured, drops every notification rather than accepting.
2. **Implemented dispatch** — named change handlers + lifecycle handlers, isolated
   so one handler raising never breaks the batch or the 202 response.
3. **Lifecycle handling** — ``reauthorizationRequired`` / ``subscriptionRemoved``
   / ``missed`` are parsed and routed (the reference ignored them).
4. **Replay de-duplication** — Graph retries for up to 4 h and may redeliver; a
   bounded LRU (or your durable hook) drops repeats so side effects fire once.
5. **The 3-second response rule** — :func:`build_graph_webhook_router` answers
   ``202`` immediately and processes in a tracked background task, so handler
   latency never makes Graph mark the subscription "slow" and drop it.

Wiring (the integrator owns this; mount the router *after* the app is built,
DESIGN §10.3)::

    from fastapi import Depends
    from agent_sdk.auth.middleware import unauth_rate_limit
    from agent_sdk.contrib.webhooks import (
        WebhookDispatcher, build_graph_webhook_router,
    )

    dispatcher = WebhookDispatcher(
        expected_client_state=settings.webhook_client_state,  # fail-closed
    )
    dispatcher.on("default", handle_mail_change)
    dispatcher.on_lifecycle("reauthorizationRequired", reauthorize_handler)

    app = agent.build()
    app.include_router(build_graph_webhook_router(
        dispatcher,
        # Graph is unauthenticated — DO NOT add Depends(require_identity).
        # DO bound per-IP flooding of this public endpoint:
        dependencies=[Depends(unauth_rate_limit)],
    ))

**Outbound subscription management** (the other half) lives in
:class:`GraphSubscriptionManager` + :class:`SubscriptionStore`, with optional
auto-renewal via :func:`webhooks_renewal_lifespan`. Create/delete inside a request
can use the delegated :class:`~agent_sdk.contrib.obo.source.GraphSource`; renewal
runs in the background and needs an *application*-credential poster (see
``subscriptions`` module docstring).

**Secrets hygiene (DESIGN §6 / standing instruction):** the ``clientState`` secret
and the ``validationToken`` are never logged or placed in an error; the dispatcher
and manager log only subscription ids (GUIDs), change/lifecycle event names,
handler names, and exception *type* names; the subscription store never persists
the secret (only a non-secret reference label).

**Operational notes (known, deliberate trade-offs — not defects):**

- *This endpoint is intentionally public.* Authenticity is ``clientState``, not
  transport auth. The fail-closed default + per-IP ``unauth_rate_limit`` are the
  controls; never bolt ``require_identity`` onto it (Graph cannot present a token).
- *In-process dedup is per-process, not durable.* The default LRU does not survive
  a restart and is not shared across replicas; a handler that must be exactly-once
  across restarts/replicas should pass a durable ``seen=`` predicate (e.g. a row
  insert with a unique constraint) — the in-memory cap only bounds repeats within
  one run. The in-memory default *releases* a claim when its handler fails, so a
  later Graph re-delivery is retried rather than dropped; a durable ``seen`` hook
  owns its own policy (record-on-check drops a failed event's repeat, so
  record-on-success in the hook if you need the retry).
- *``subscriptionRemoved`` / ``missed`` need a resync, not just a 202.* Acking
  these lifecycle events is not enough — ``subscriptionRemoved`` requires
  recreating the subscription + a delta resync, ``missed`` a full delta resync, or
  changes are silently lost. See :func:`recommended_action`.
- *``max_in_flight`` backpressure sheds, it does not queue.* Over the cap, a batch
  is dropped and relies on Graph's retry (up to 4 h) to redeliver — favor a higher
  cap + faster handlers over silent loss under sustained load.
- *Background renewal needs app-cred auth.* :func:`webhooks_renewal_lifespan` runs
  outside any request, so its manager's Graph poster must use application
  credentials, not a per-request delegated/OBO token.
"""

from __future__ import annotations

from .dispatch import (
    DispatchReport,
    LIFECYCLE_WILDCARD,
    WebhookDispatcher,
)
from .graph import build_graph_webhook_router
from .models import (
    DEFAULT_MAX_ITEMS,
    LIFECYCLE_EVENTS,
    LIFECYCLE_MISSED,
    LIFECYCLE_REAUTH,
    LIFECYCLE_REMOVED,
    ChangeNotification,
    LifecycleNotification,
    ParsedBatch,
    parse_batch,
)
from .subscriptions import (
    LIFECYCLE_ACTIONS,
    VALID_CHANGE_TYPES,
    GraphSubscriptionManager,
    SubscriptionStore,
    recommended_action,
    validate_change_type,
    validate_guid,
    validate_notification_url,
    validate_resource,
    webhooks_renewal_lifespan,
)

__all__ = [
    # receiver
    "WebhookDispatcher",
    "DispatchReport",
    "build_graph_webhook_router",
    "LIFECYCLE_WILDCARD",
    # models
    "ChangeNotification",
    "LifecycleNotification",
    "ParsedBatch",
    "parse_batch",
    "LIFECYCLE_EVENTS",
    "LIFECYCLE_REAUTH",
    "LIFECYCLE_REMOVED",
    "LIFECYCLE_MISSED",
    "DEFAULT_MAX_ITEMS",
    # subscriptions
    "SubscriptionStore",
    "GraphSubscriptionManager",
    "webhooks_renewal_lifespan",
    "recommended_action",
    "LIFECYCLE_ACTIONS",
    "validate_guid",
    "validate_change_type",
    "validate_resource",
    "validate_notification_url",
    "VALID_CHANGE_TYPES",
]
