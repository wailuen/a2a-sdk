"""A2UI v0.9.1 translator (DESIGN.md §5.4) — single translator feeding both
A2A DataPart artifacts and AG-UI A2UI_UPDATE CUSTOM events.

Per artifact ``translate()`` computes ONE ``list[dict]`` (never a bare dict)
holding the full self-cleaning sequence::

    createSurface → updateComponents → updateDataModel → deleteSurface

- every message carries ``version: "v0.9.1"``
- the first updateComponents establishes exactly one component, id "root"
- the data binding is a direct ``data: {"path": "/root"}`` prop (no props
  wrapper); the component discriminator key is ``component``
- updateDataModel carries ``path``/``value`` directly (no data wrapper)
- MarketBriefing's value is its ``to_markdown()`` string (prose exception) —
  and, because ``to_markdown()`` is deliberately kept free of the base
  class's ``metadata`` suffix (unlike ``to_plain_text()``), a MarketBriefing's
  ``metadata`` disclosure envelope never reaches this surface at all. This is
  a DOCUMENTED carve-out (RT-008), not a gap: see DESIGN.md §4.3 for the full
  rationale and ``tests/test_dbg6_market_briefing_metadata_carveout.py`` for
  the pin. Every other content type's ``metadata`` reaches A2UI via ``wire()``
  below unchanged.

``translate()``'s return value is a computed sequence, not a wire delivery
unit. Delivery callers (``agent/runner.py::build_artifact``,
``routes/ag_ui.py``'s ``ArtifactEvent`` branch) MUST pass it through
``agent/runner.py::split_a2ui_delivery_validated()`` — never call this
module's own ``split_a2ui_delivery()`` directly from a delivery caller
(RT-001: a transport that split without validating first shipped malformed
A2UI silently instead of failing the run) — and deliver the two returned
halves as two independently folded arrays. See ``split_a2ui_delivery()``'s
own docstring for why the split exists at all: a spec-conformant A2UI
v0.9.1 Path-A renderer folds one delivered message array atomically and
paints once after the fold, so ``deleteSurface`` can never share a delivered
array with its own surface's create/populate messages.

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
    # Set only by for_custom_emit(): AG-UI CUSTOM emission skips catalog
    # negotiation (LRN-049).
    any_catalog: bool = False

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
            # GH-180: A2UI v0.9.1 negotiation — a domain surface is only sent
            # when the client declared its catalog. A2A has no silent-ignore
            # safety net. AG-UI CUSTOM goes through for_custom_emit() instead.
            return self.any_catalog or model_cls.catalog_id in self.catalogs
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
        return A2uiCapabilities(
            tier="core+extended", catalogs=list(self.catalogs), any_catalog=True
        )


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
    try:
        # isinstance() kept as the ternary's own condition (not hoisted to a
        # bool) so mypy narrows payload to MarketBriefing for to_markdown().
        # RT-008: to_markdown() carries no metadata suffix, so a MarketBriefing's
        # metadata never reaches this surface — see the module docstring above
        # and DESIGN.md §4.3. Deliberate, not a gap; do not "fix" by switching
        # this branch to wire()/to_plain_text() without re-reading both.
        value: Any = (
            payload.to_markdown() if isinstance(payload, MarketBriefing) else payload.wire()
        )
    except Exception as exc:
        # SI-2 (RT-004): this is the actual reachable call site for a
        # domain card's wire()/to_markdown() exception — it runs BEFORE
        # runner.py's split_a2ui_delivery_validated ever gets a chance to
        # re-check wire(), so an unguarded raise here previously escaped
        # both transports unwrapped, with str(exc) intact. Report only the
        # exception's type, never str(exc), and suppress chaining
        # (`from None`, not `from exc`) — a transport that logs this via
        # logger.exception() (AG-UI's stream handler) walks the full
        # __cause__ chain and would reprint exc's own message otherwise.
        method = "to_markdown" if isinstance(payload, MarketBriefing) else "wire"
        raise ValueError(
            f"{cls.__name__!r} ({payload.data_type!r}): {method}() raised "
            f"{type(exc).__name__}"
        ) from None
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


def split_a2ui_delivery(
    messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Partition a ``translate()`` sequence into (open, close) for two
    independently-folded wire deliveries.

    Critical protocol-conformance fix: the A2UI v0.9.1 client contract folds
    ONE delivered message array atomically and paints once after the fold;
    ``deleteSurface``'s unmount+unsubscribe happens DURING that fold, before
    the paint. ``translate()`` computes ``createSurface``/``updateComponents``/
    ``updateDataModel``/``deleteSurface`` as one logical sequence, but if that
    whole sequence were handed to a strictly spec-conformant Path-A renderer
    as a single delivered array, the renderer would unmount the surface
    before ever painting it — nothing would render, for every artifact, on
    any consumer that has no private knowledge of this SDK's renderer
    internals.

    The fix is at the delivery boundary, not inside ``translate()``: split
    the sequence into an *open* array (``createSurface``, ``updateComponents``,
    ``updateDataModel``) and a *close* array (``deleteSurface``), and deliver
    them as two separate wire units — two DataParts on one A2A artifact, or
    two AG-UI ``A2UI_UPDATE`` CUSTOM events, always open before close. Each
    array then gets its own ordinary atomic fold-and-paint pass: the open
    array's pass paints the surface; the close array's pass touches no
    surface (nothing to (re)paint) and closes the registry entry only once
    already-painted DOM. No renderer needs private knowledge of a
    "post-paint" convention — this is ordinary sequential per-array
    processing, exactly what the spec's fold-once-per-array contract already
    guarantees.
    """
    close = [m for m in messages if "deleteSurface" in m]
    open_ = [m for m in messages if "deleteSurface" not in m]
    return open_, close


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
    """Apply a single A2UI v0.9.1 ``updateDataModel`` patch to *model* in-place.

    *pointer* — a root-relative JSON Pointer (RFC 6901) starting with ``/``,
    with one spec exception and one security guard:

    - Whole-model replace: A2UI v0.9.1 defines "omit path or use ``/`` to
      replace the whole data model". ``""`` and ``"/"`` are handled
      identically, BEFORE the root-relative check, as a genuine whole-model
      replace (``model.clear(); model.update(value)`` — every existing
      top-level key discarded). Because this is an in-place mutator (it cannot
      reassign the caller's ``model`` reference), *value* must be a ``dict``;
      any other type raises ``ValueError``.
    - Parent-escape guard (security-motivated, stricter than the renderer, not
      RFC 6901-mandated): a pointer with a DECODED token EQUAL to ``".."``
      (e.g. ``/foo/../bar``, ``/..``) is rejected. This is the *only* escape
      spelling: the check runs after ``~1``/``~0`` decoding and ``".."`` has no
      tilde form, so a token equals ``".."`` iff its raw form was literally
      ``".."`` — nothing can hide an escape from it. It is a per-token equality
      check, never a substring test: a key that merely CONTAINS ``..`` (e.g.
      ``..foo``) or a ``~1``-formed literal key holding ``/`` (e.g. ``foo/..``
      from ``/foo~1../bar``) is a real, settable key. An EMPTY path segment is
      likewise NOT an escape — per RFC 6901 it addresses the empty-string key
      ``model[""]``, an ordinary key within the component root (``//bar`` →
      ``{"": {"bar": ...}}``); every empty-segment spelling is accepted
      uniformly.

    *value* semantics (A2UI v0.9.1):
    - ``MISSING`` → delete the target key at *pointer* (omitting ``value`` on
      the wire means delete-at-path). No-op if the leaf key is absent — but
      "no-op" means only the LEAF write is skipped: an absent *intermediate*
      segment is still scaffolded (see traversal below), so the model is not
      guaranteed byte-for-byte unchanged. For the whole-model forms
      (``""``/``"/"``), ``MISSING`` is a no-op: this is an SDK-defined
      resolution of a genuinely ambiguous rule composition — the spec's "omit
      path/``/`` = whole model" and "omit value = delete key at path" rules,
      composed, leave the delete with no single key to target. Both this helper
      and the SDK renderer (``pointerSet``'s empty-tokens branch) no-op here,
      but a spec-literal third-party peer could read omit-path+omit-value as
      clear-the-model; treat the no-op as this SDK's choice, not a spec
      certainty. (The spec-supported clear is an explicit ``value={}``, honored
      as a whole-model replace.) Pinned by
      ``test_..._whole_model_missing_is_noop_per_spec_no_key_at_path``.
    - ``None`` → set the target field to JSON null.
    - Any other value → replace the target field.

    Traversal (ordinary, non-whole-model pointers) is one walk shared by the
    set and delete branches, mirroring ``pointerSet``'s traverse-then-branch
    shape, under a single reconciliation rule applied to every intermediate
    node type: **traverse like ``pointerSet``, but never overwrite/destroy a
    pre-existing non-dict node.** Consequences:

    - Absent intermediate key → scaffold an empty dict (destroys nothing →
      CONVERGES; deleting ``/a/b/c`` on ``{}`` yields ``{a: {b: {}}}`` on both
      sides, additive scaffolding + no-op leaf pop).
    - Pre-existing dict intermediate → descend (CONVERGES).
    - Pre-existing scalar or list intermediate → refuse to clobber (set raises,
      delete no-ops), where ``pointerSet`` destructively overwrites it with
      ``{}``/``[]`` (DIVERGES — see divergences below).

    Deliberate divergences from ``pointerSet`` — FOUR total, all latent (never
    reached by ``translate()``, which only ever sets an explicit ``dict`` at
    the flat ``/root`` pointer), each pinned by a live-node cross-check in
    tests/test_a2ui_wire.py:

    - Numeric token → literal string dict key here, list index in the renderer
      (``/metrics/0`` → ``{"metrics": {"0": ...}}`` here vs. a JS array there).
    - Scalar/list intermediate → preserved here (set raises, delete no-ops),
      destructively overwritten with ``{}``/``[]`` in the renderer
      (``pointerSet({"a": 5}, "/a/b/c", undefined)`` → ``{"a": {"b": {}}}``).
    - Whole-model replace with a non-``dict`` value → ``ValueError`` here (an
      in-place mutator cannot write a non-object ``dataModel``), returned
      verbatim by the renderer (``pointerSet({}, "/", "scalar")`` →
      ``"scalar"``).
    - A genuine ``".."`` token → rejected here (parent-escape guard), treated
      as an ordinary literal key by the renderer
      (``pointerSet({}, "/foo/../bar", "X")`` → ``{"foo": {"..": {"bar":
      "X"}}}``).

    The round-by-round rationale for these rules (RT-001/RT-002/RT-002a-c,
    RT-JSON-POINTER-001, RT-EMPTY-SEGMENT-001) lives in CHANGELOG 0.5.44 and
    git history; this docstring states the resulting contract only.
    """
    # A2UI v0.9.1 whole-data-model replace: "omit path or use / to replace
    # the whole data model" — both spellings handled identically, BEFORE the
    # root-relative check below (RT-002: "/" is a spec ALIAS for the omitted
    # path here, not an ordinary one-segment pointer to model[""]).
    if pointer == "" or pointer == "/":
        if value is MISSING:
            return
        if not isinstance(value, dict):
            raise ValueError(
                f"whole-data-model replace (pointer {pointer!r}) requires an "
                f"object value; got {type(value).__name__}"
            )
        model.clear()
        model.update(value)
        return

    # M2: pointer scope guard — JSON Pointers here are always component-root-
    # relative and must start with "/". Empty path segments (a "//" prefix, or
    # "/a//b", "/a/") are NOT an escape: per RFC 6901 they address the
    # empty-string key, an ordinary key WITHIN the component-root model
    # (model[""]), never the envelope or a parent — so every empty-segment
    # spelling is accepted uniformly and converges with the renderer's
    # pointerSet (see the RT-EMPTY-SEGMENT-001 docstring note; a prior revision
    # rejected only the "//" prefix, blocking one spelling while accepting the
    # equivalent /a//b and /a/, which is no boundary at all). The genuine
    # parent-escape guard is the ".." decoded-token check below.
    if not pointer.startswith("/"):
        raise ValueError(f"JSON Pointer must be root-relative (start with /); got {pointer!r}")

    # RFC 6901 token decoding: ~1 → /, ~0 → ~
    tokens = [t.replace("~1", "/").replace("~0", "~") for t in pointer[1:].split("/")]
    # Parent-escape guard: reject ONLY a decoded token EQUAL to "..". That is
    # the one and only spelling of a parent-escape segment — and this check is
    # complete:
    #   * It runs AFTER ~1/~0 decoding, and ".." has no tilde form (neither ~0
    #     → "~" nor ~1 → "/" can produce a "."), so a token equals ".." iff its
    #     raw form was literally "..". Nothing can hide a ".." segment from
    #     this check.
    #   * It is checked per DECODED TOKEN, never as a substring of *pointer* or
    #     of a token, so a legitimate RFC 6901 key that merely CONTAINS ".."
    #     (e.g. "..foo") or a "/" (e.g. the ~1-formed literal key "foo/.." from
    #     "/foo~1../bar") is a real, settable key — NOT an escape. A "/" inside
    #     a decoded token can ONLY come from ~1 (a literal key character, never
    #     a path separator: the split on "/" already happened), so any
    #     substring test like "/.." in t or t.startswith("../") would fire
    #     SOLELY on such ~1-formed literal keys, catching zero genuine escapes
    #     while over-rejecting valid pointers and diverging from the renderer
    #     (a2ui.js pointerSet writes {"foo/..": {"bar": ...}} for that pointer).
    #     Such substring clauses were removed here — see the docstring's
    #     RT-JSON-POINTER-001 note.
    if any(t == ".." for t in tokens):
        raise ValueError(f"JSON Pointer escapes component root: {pointer!r}")

    leaf = tokens[-1]

    # Navigate to the parent of the target key, unconditionally — mirrors
    # a2ui.js's pointerSet's traverse-then-branch shape (creating missing
    # intermediate dicts as needed) for BOTH the set and delete (MISSING)
    # branches (GH-126 follow-up). Object-keyed only: numeric tokens are NOT
    # treated as array indices here — see the docstring's RT-002a note. A
    # pre-existing non-dict node along the path (list OR scalar) is not
    # scaffolded over here, unlike pointerSet: the set branch raises, the
    # delete branch silently no-ops — see the docstring's RT-002a/RT-002b.
    target: Any = model
    for token in tokens[:-1]:
        if not isinstance(target, dict):
            if value is MISSING:
                return
            raise ValueError(f"Cannot traverse non-dict at token {token!r} in {pointer!r}")
        target = target.setdefault(token, {})

    if not isinstance(target, dict):
        if value is MISSING:
            return
        raise ValueError(f"Parent of leaf key {leaf!r} is not a dict in {pointer!r}")

    if value is MISSING:
        # A2UI v0.9.1: an updateDataModel patch with no "value" key deletes
        # the key at *pointer* — no-op if it is already absent.
        target.pop(leaf, None)
        return

    # Explicit None → JSON null; any other value replaces the field.
    target[leaf] = value
