"""Parsed Microsoft Graph change-notification payloads (DESIGN §9).

Graph delivers notifications as a batch::

    {"value": [ {<notification>}, {<notification>}, ... ]}

Two shapes share the envelope, distinguished by the presence of
``lifecycleEvent``:

- **change notifications** carry ``changeType`` / ``resource`` / ``resourceData``
  and tell you *something changed* — re-fetch the resource for the new state;
  ``resourceData`` is only an id/etag pointer, never trusted content.
- **lifecycle notifications** carry ``lifecycleEvent`` (``reauthorizationRequired``
  / ``subscriptionRemoved`` / ``missed``) and tell you *the subscription itself*
  needs attention — they have no ``resource``/``resourceData``.

These frozen dataclasses are the parsed, validated views handed to dispatch
handlers. Parsing is *tolerant*: a malformed entry is skipped (counted, not
raised) so one bad item in a batch never drops the whole batch — and a bounded
``max_items`` caps a hostile oversized batch. ``client_state`` is parsed but is
NEVER logged or placed in an error (it is the shared secret).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# The three Graph lifecycle events (subscription-level, not resource-level).
LIFECYCLE_REAUTH = "reauthorizationRequired"
LIFECYCLE_REMOVED = "subscriptionRemoved"
LIFECYCLE_MISSED = "missed"
LIFECYCLE_EVENTS = frozenset({LIFECYCLE_REAUTH, LIFECYCLE_REMOVED, LIFECYCLE_MISSED})

# Defensive cap: a single POST that claims thousands of notifications is hostile
# (Graph batches are small). Anything past this is truncated, counted, dropped.
DEFAULT_MAX_ITEMS = 256


@dataclass(frozen=True)
class ChangeNotification:
    """A single resource-change notification (one entry of ``value[]``)."""

    notification_id: str | None
    subscription_id: str
    change_type: str
    resource: str
    tenant_id: str | None
    client_state: str | None
    expiration: str | None
    resource_data: dict[str, Any]

    @classmethod
    def from_item(cls, item: dict[str, Any]) -> "ChangeNotification":
        sub = item.get("subscriptionId")
        if not isinstance(sub, str) or not sub:
            raise ValueError("notification missing subscriptionId")
        rd = item.get("resourceData")
        return cls(
            notification_id=_opt_str(item.get("id")),
            subscription_id=sub,
            change_type=_req_str(item.get("changeType"), "changeType"),
            resource=_req_str(item.get("resource"), "resource"),
            tenant_id=_opt_str(item.get("tenantId")),
            client_state=_opt_str(item.get("clientState")),
            expiration=_opt_str(item.get("subscriptionExpirationDateTime")),
            resource_data=rd if isinstance(rd, dict) else {},
        )

    # The id used for replay de-duplication. Graph's per-notification ``id`` is
    # the natural key; if absent, fall back to a composite so a malformed-but-
    # repeated item still de-dupes within one process run.
    @property
    def dedup_key(self) -> str:
        if self.notification_id:
            return self.notification_id
        return f"{self.subscription_id}:{self.change_type}:{self.resource}"

    # ``resourceData`` is only a pointer (id + etag); a handler must re-fetch the
    # resource for actual content. These accessors save hand-parsing OData keys.
    @property
    def resource_data_id(self) -> str | None:
        rid = self.resource_data.get("id")
        return rid if isinstance(rid, str) and rid else None

    @property
    def resource_etag(self) -> str | None:
        etag = self.resource_data.get("@odata.etag")
        return etag if isinstance(etag, str) and etag else None


@dataclass(frozen=True)
class LifecycleNotification:
    """A single subscription-lifecycle notification (one entry of ``value[]``)."""

    subscription_id: str
    lifecycle_event: str
    tenant_id: str | None
    client_state: str | None
    expiration: str | None

    @classmethod
    def from_item(cls, item: dict[str, Any]) -> "LifecycleNotification":
        sub = item.get("subscriptionId")
        if not isinstance(sub, str) or not sub:
            raise ValueError("lifecycle notification missing subscriptionId")
        event = _req_str(item.get("lifecycleEvent"), "lifecycleEvent")
        return cls(
            subscription_id=sub,
            lifecycle_event=event,
            tenant_id=_opt_str(item.get("tenantId")),
            client_state=_opt_str(item.get("clientState")),
            expiration=_opt_str(item.get("subscriptionExpirationDateTime")),
        )


@dataclass(frozen=True)
class ParsedBatch:
    """The split, parsed result of one POST body."""

    changes: list[ChangeNotification]
    lifecycles: list[LifecycleNotification]
    skipped: int  # malformed entries dropped
    truncated: int  # entries past max_items dropped


def parse_batch(payload: Any, *, max_items: int = DEFAULT_MAX_ITEMS) -> ParsedBatch:
    """Split a Graph notification POST body into change + lifecycle notifications.

    Tolerant by design: a non-dict body, a missing/!list ``value``, or any
    individual malformed entry yields empty/partial results with a ``skipped``
    count rather than an exception — the receiver must always answer Graph 202,
    so parsing never raises on bad input.
    """
    changes: list[ChangeNotification] = []
    lifecycles: list[LifecycleNotification] = []
    skipped = 0
    truncated = 0

    items = payload.get("value") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        # A lone validation POST has no body; a malformed body has no value[].
        return ParsedBatch(changes, lifecycles, skipped=0, truncated=0)

    if len(items) > max_items:
        truncated = len(items) - max_items
        items = items[:max_items]

    for item in items:
        if not isinstance(item, dict):
            skipped += 1
            continue
        try:
            if item.get("lifecycleEvent") is not None:
                lifecycles.append(LifecycleNotification.from_item(item))
            else:
                changes.append(ChangeNotification.from_item(item))
        except ValueError:
            skipped += 1
    return ParsedBatch(changes, lifecycles, skipped=skipped, truncated=truncated)


def _req_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"notification field {field!r} missing or not a string")
    return value


def _opt_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


__all__ = [
    "ChangeNotification",
    "LifecycleNotification",
    "ParsedBatch",
    "parse_batch",
    "LIFECYCLE_EVENTS",
    "LIFECYCLE_REAUTH",
    "LIFECYCLE_REMOVED",
    "LIFECYCLE_MISSED",
    "DEFAULT_MAX_ITEMS",
]
