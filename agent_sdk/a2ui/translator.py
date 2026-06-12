"""A2UI v0.9.1 translator (DESIGN.md §5.4) — single translator feeding both
A2A DataPart artifacts and AG-UI A2UI_UPDATE CUSTOM events.

Per artifact it emits ONE ``list[dict]`` (never a bare dict) holding the
full self-cleaning sequence::

    createSurface → updateComponents → updateDataModel → deleteSurface

- every message carries ``version: "v0.9.1"``
- the first updateComponents establishes exactly one component, id "root"
- the data binding is a direct ``data: {"path": "/root"}`` prop (no props
  wrapper); the component discriminator key is ``component``
- updateDataModel carries ``path``/``value`` directly (no data wrapper)
- MarketBriefing's value is its ``to_markdown()`` string (prose exception)
- deleteSurface closes the surface's update lifecycle; rendering is
  show-then-close (§7.1)

Gating happens here (capabilities resolved by the route, §5.4): Extended
profile types need ``tier="core+extended"``; domain cards need their
``catalog_id`` listed in the client's catalogs. Gated off → ``None``; the
caller still ships the TextPart fallback — nothing is silently dropped.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from ..models.content_types import (
    A2UI_VERSION,
    CATALOG_ID,
    ContentModel,
    MarketBriefing,
)


@dataclass(slots=True)
class A2uiCapabilities:
    """Client capability claim. Absent claim → core tier, standard catalog."""

    tier: str = "core"
    catalogs: list[str] = field(default_factory=lambda: [CATALOG_ID])

    @classmethod
    def from_metadata(cls, raw: Any) -> "A2uiCapabilities":
        if not isinstance(raw, dict):
            return cls()
        tier = raw.get("tier") or "core"
        catalogs = raw.get("catalogs")
        if not isinstance(catalogs, list) or not catalogs:
            catalogs = [CATALOG_ID]
        return cls(tier=str(tier), catalogs=[str(c) for c in catalogs])

    @property
    def extended(self) -> bool:
        # spec token "core+extended"; substring match kept for back-compat
        return "extended" in self.tier

    def allows(self, model_cls: type[ContentModel]) -> bool:
        if model_cls.catalog_id != CATALOG_ID:
            # domain gating: tier alone never unlocks domain types
            return model_cls.catalog_id in self.catalogs
        if model_cls.extended:
            return self.extended
        return True


def translate(
    payload: ContentModel,
    *,
    capabilities: A2uiCapabilities | None = None,
    surface_id: str | None = None,
) -> list[dict[str, Any]] | None:
    """Full four-message sequence for one artifact, or None when the type
    is gated off for this client."""
    caps = capabilities or A2uiCapabilities()
    cls = type(payload)
    if not caps.allows(cls):
        return None

    sid = surface_id or f"surface-{uuid.uuid4().hex}"
    value: Any = (
        payload.to_markdown() if isinstance(payload, MarketBriefing) else payload.wire()
    )
    return [
        {
            "version": A2UI_VERSION,
            "createSurface": {"surfaceId": sid, "catalogId": cls.catalog_id},
        },
        {
            "version": A2UI_VERSION,
            "updateComponents": {
                "surfaceId": sid,
                "components": [
                    {"id": "root", "component": cls.component, "data": {"path": "/root"}}
                ],
            },
        },
        {
            "version": A2UI_VERSION,
            "updateDataModel": {"surfaceId": sid, "path": "/root", "value": value},
        },
        {
            "version": A2UI_VERSION,
            "deleteSurface": {"surfaceId": sid},
        },
    ]
