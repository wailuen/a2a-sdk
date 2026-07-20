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
profile types need ``tier="core+extended"``; domain cards are emitted freely
whenever tier is active (consumers silently ignore unknown CUSTOM events per
AG-UI spec) — only ``tier="none"`` suppresses them (GH-56). Gated off →
``None``; the caller still ships the TextPart fallback — nothing is silently
dropped.
"""

from __future__ import annotations

import uuid
import warnings
from dataclasses import dataclass, field
from typing import Any

from ..models.content_types import (
    A2UI_VERSION,
    CATALOG_ID,
    ContentModel,
    MarketBriefing,
)

# Sentinel for "field absent from update dict" — distinct from None (explicit JSON null).
MISSING = object()


@dataclass(slots=True)
class A2uiCapabilities:
    """Client capability claim. Absent claim → core tier, standard catalog
    (payload-parse default, used by the constructor and ``from_metadata()``
    only).

    Do NOT align the transport route boundary to this default. The route
    boundary resolves an absent opt-in via ``gated()``, which fail-closes to
    ``tier="none"`` — see LRN-046/LRN-115. These two defaults intentionally
    diverge: this one is a fail-open convenience for already-trusted input,
    that one is a fail-closed security gate for untrusted transport input.
    """

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

    @classmethod
    def gated(cls, opted_in: bool, raw: Any) -> "A2uiCapabilities":
        """Fail-closed capability resolution shared across transports (C-006).

        *opted_in* is the transport-specific opt-in signal — A2A: the
        A2UI extension URI was present in ``X-A2A-Extensions``; AG-UI:
        ``forwardedProps.a2uiClientCapabilities`` was present. A client that
        never opts in gets ``tier="none"`` regardless of *raw* (LRN-046):
        this is the one place that default is defined, so no transport can
        independently drift back to fail-open.
        """
        if not opted_in:
            return cls(tier="none", catalogs=[])
        return cls.from_metadata(raw)

    @property
    def extended(self) -> bool:
        # spec token "core+extended"; substring match kept for back-compat
        return "extended" in self.tier

    def allows(self, model_cls: type[ContentModel]) -> bool:
        if self.tier == "none":
            return False
        if model_cls.catalog_id != CATALOG_ID:
            # Domain types: emit freely when tier is active — consumers silently
            # ignore unknown CUSTOM events (AG-UI spec).  Catalog gating only
            # applied when tier=="none" (already returned False above).
            return True
        if model_cls.extended:
            return self.extended
        return True

    def for_custom_emit(self) -> "A2uiCapabilities":
        """Capabilities for AG-UI CUSTOM event gating (LRN-049).

        Per spec, CUSTOM events are suppressed only when tier=='none'.
        Extended/catalog membership is irrelevant on the AG-UI path because
        consumers silently ignore unknown CUSTOM types — suppressing them
        breaks discovery without any security benefit.

        DELIBERATE, NOT A GAP: this also means a client that declares
        ``tier="core"`` (no Extended) still receives in-catalog Extended
        Standard-Profile types (e.g. WaterfallChart) over AG-UI — the caller's
        real tier is intentionally discarded here, unlike ``allows()`` used
        directly on the A2A DataPart path, which DOES enforce Extended-tier
        gating for in-catalog types. This asymmetry is correct: AG-UI's
        silent-ignore-unknown-CUSTOM-event convention is the safety net that
        A2A DataPart lacks, so withholding data here has no protective value
        and only breaks graceful degradation. Reviewed 2026-07-20 (GH-124,
        closed as not-a-bug) after a fresh conformance audit re-raised it —
        see the pinning test
        tests/test_rt001_ag_ui_custom_extended_gate.py::test_extended_type_emits_a2ui_update_under_tier_core
        before "fixing" this.
        """
        if self.tier == "none":
            return self
        return A2uiCapabilities(tier="core+extended", catalogs=list(self.catalogs))


def translate(
    payload: ContentModel,
    *,
    capabilities: A2uiCapabilities | None = None,
    surface_id: str | None = None,
    send_data_model: bool = False,
    theme: dict[str, Any] | None = None,
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
    create_surface_params: dict[str, Any] = {
        "surfaceId": sid,
        "catalogId": cls.catalog_id,
    }
    if send_data_model:
        create_surface_params["sendDataModel"] = True
    if theme is not None:
        create_surface_params["theme"] = theme
    return [
        {
            "version": A2UI_VERSION,
            "createSurface": create_surface_params,
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


class SurfaceRegistry:
    """Tracks open surfaces for callers that drive streaming A2UI lifecycles.

    Intended for long-lived sessions that emit createSurface/deleteSurface
    messages incrementally (e.g. AG-UI CUSTOM event streams).  The stateless
    ``translate()`` helper above does not use this — it emits its own
    self-contained four-message sequence.
    """

    def __init__(self) -> None:
        self._open: set[str] = set()

    def open(self, surface_id: str) -> None:
        # M1: duplicate createSurface — warn rather than raise so existing
        # renders are not abruptly broken by a re-open attempt.
        if surface_id in self._open:
            warnings.warn(
                f"createSurface called for already-open surface {surface_id!r}; "
                "ignoring duplicate",
                stacklevel=2,
            )
            return
        self._open.add(surface_id)

    def close(self, surface_id: str) -> None:
        self._open.discard(surface_id)

    def is_open(self, surface_id: str) -> bool:
        return surface_id in self._open


def apply_data_model_update(
    model: dict[str, Any],
    pointer: str,
    value: Any,
) -> None:
    """Apply a single updateDataModel patch to *model* in-place.

    *pointer* must be a root-relative JSON Pointer (RFC 6901) starting with
    ``/``.  Pointers that would escape the component root (starting with ``//``
    or containing ``.``) are rejected — scope is always the component root,
    never the message envelope.

    *value* semantics:
    - Pass ``MISSING`` to leave the target key unchanged (absent-from-update).
    - Pass ``None`` to explicitly set the target field to JSON null.
    - Any other value replaces the target field.
    """
    # M2: pointer scope guard — JSON Pointers here are always component-root-
    # relative.  A double-slash prefix or a dot-segment would escape that scope.
    if not pointer.startswith("/"):
        raise ValueError(f"JSON Pointer must be root-relative (start with /); got {pointer!r}")
    if pointer.startswith("//") or "/.." in pointer or pointer == "/..":
        raise ValueError(f"JSON Pointer escapes component root: {pointer!r}")

    # M3: absent-value sentinel — nothing to do.
    if value is MISSING:
        return

    # Navigate to the parent of the target key.
    # RFC 6901 token decoding: ~1 → /, ~0 → ~
    tokens = [t.replace("~1", "/").replace("~0", "~") for t in pointer[1:].split("/")]
    target = model
    for token in tokens[:-1]:
        if not isinstance(target, dict):
            raise ValueError(f"Cannot traverse non-dict at token {token!r} in {pointer!r}")
        target = target.setdefault(token, {})

    leaf = tokens[-1]
    if not isinstance(target, dict):
        raise ValueError(f"Parent of leaf key {leaf!r} is not a dict in {pointer!r}")
    # Explicit None → JSON null (M3); any other value → set field.
    target[leaf] = value
