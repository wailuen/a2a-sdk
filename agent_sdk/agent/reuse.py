"""Reusable and ReuseKind — cross-turn reference for tool-resolved values
(GH-148 / LRN-355).

``run_loop``'s only cross-turn memory is replaying the full ``messages``
transcript verbatim; the task-local result cache in ``loop.py`` only dedupes
byte-identical repeat calls WITHIN one task. Nothing let the model reference
a value it resolved in an earlier turn without retyping it from memory —
live testing found the model substitutes a different-but-real, WRONG entity
id in most runs, a silent data-correctness failure with no validation-layer
signal (the substituted value is itself a real, valid id).

A tool marks a return value reusable via ``Reusable(value=result,
kind="entity_id", label="PT IMC Pelita Logistik")``. ``agent/loop.py``
unwraps it before the model sees the result (the model receives ``.value``)
and folds a ``__resolved__`` marker — ``{"kind", "label", "value"}`` — into
that tool call's result block in ``messages``, the same JSON block already
folded today. No new store, no new ``TaskRecord`` field, no expiry rule: the
mechanism rides ``messages`` — but ``messages`` itself only survives a
request boundary on a transport whose fold preserves tool-result blocks
(RT-001).

**A2A and AG-UI both carry it across a request boundary, by two different
routes (RT-A-004).** Each new A2A ``TaskRecord`` is seeded via
``TaskStore.context_messages()``, which returns the prior task's
Converse-format ``messages`` — server-persisted, never round-tripped
through the client — directly into ``record.messages``, so a marker folded
in turn N survives into turn N+1's fresh ``run_loop`` call as part of the
model-visible transcript itself. AG-UI's ``routes/ag_ui.py::_fold_history``
collapses every resent message, including a prior tool-result block, down to
a single ``{"text": ...}`` entry built only from ``type == "text"`` parts, so
that route CANNOT put a marker back into the model-visible ``messages`` the
same way — instead it calls ``TaskStore.context_reusable_messages(thread_id)``
(``thread_id`` and ``context_id`` are the same value there) and passes the
result to ``run_loop`` as ``extra_resolved_messages``: scanned to seed
``resolved_index`` only, never appended to ``messages`` and never shown to
the model, so AG-UI's smaller, text-only transcript is unchanged.

``context_reusable_messages()`` is NOT ``context_messages()`` (RT-001): each
new AG-UI ``TaskRecord.messages`` starts fresh from that run's own folded
text only — unlike A2A, it never inherits the prior task's ``messages`` — so
a marker folded while completing run N lives ONLY in run N's own persisted
``messages``. Seeding from ``context_messages()`` (the single most recent
terminal task) would decay after exactly one intervening, unrelated run: as
soon as run N+1 completes with no marker of its own, it becomes the newest
terminal task and run N+2's seed goes empty, silently reopening GH-148's
wrong-but-real-id failure. ``context_reusable_messages()`` instead scans
EVERY terminal task in the thread, so a marker survives for the life of the
conversation regardless of what runs in between.

**Neither carrier ever honours an admin api_key identity's cross-identity
override — on EITHER transport (RT-004, extending RT-009).**
``context_reusable_messages()`` never did: its identity filter applies even
to an admin caller, full stop, so AG-UI's carrier never contains another
identity's marker to begin with. ``context_messages()`` used to special-case
an admin api_key identity (a "operator task inspection" bypass, RT-003) —
but that bypass fed straight into a NEW task's model-facing
``record.messages``, not a read-only view, so it was itself the same covert
side channel this section already closed for
``context_reusable_messages()``: an admin api_key caller who supplied
another identity's contextId/threadId would inherit that identity's
transcript — markers included, before RT-003 papered over just the marker
half — into the admin's own continuation turn. Removed rather than
mitigated (RT-004): ``context_messages()`` is now identity-scoped exactly
like ``context_reusable_messages()``, no exception for admin api_key
identities. Genuine operator inspection of another identity's task remains
available, safely, as a read that never seeds a new task's model context:
``GET /v1/tasks/{id}`` (``TaskStore.get()``'s own, narrower admin override,
DESIGN.md §5.1). See
``tests/test_gh148_reuse_kind_substitution.py``'s
``test_route_level_ref_substitution_survives_ag_ui_thread_continuation``,
``test_route_level_ag_ui_ref_substitution_survives_intervening_unrelated_run``
(RT-001),
``test_route_level_ag_ui_admin_key_cannot_seed_resolved_index_from_other_identity_thread``
(RT-009) and its A2A counterpart
``test_route_level_a2a_admin_key_cannot_seed_resolved_index_from_other_identity_thread``
(RT-003), for both transports proven against the real routes, not just
``run_loop`` in isolation. ``tests/test_context_reusable_messages.py`` has
the store-level coverage for both methods, including RT-010's bound on
``context_reusable_messages()`` below; RT-004's removal of
``context_messages()``'s admin bypass itself is pinned end-to-end by
``tests/test_admin_continuation_scoped_to_own_identity.py``.

An input field opts a tool into the substitution/validation contract via
``Annotated[<type>, ReuseKind("entity_id")]`` on the tool's Pydantic
``input_model``. Before invoking such a tool, ``agent/loop.py``:

- substitutes the literal token ``$ref:<kind>`` or ``$ref:<kind>:<label>``
  (to disambiguate multiple resolutions of the same kind) with the matching
  resolved value, and records the substitution as an auditable
  ``AuditEvent`` (RT-009: never a ``NoteEvent`` — that channel is folded into
  user-facing agent chat text by both transports, and this is internal
  plumbing) — never the resolved value or label itself (SI-2);
- rejects the call with a generic, SI-2-safe tool error when a raw value is
  supplied that does NOT match any ``__resolved__`` value of that kind, and
  at least one resolution of that kind exists in ``messages`` — this is the
  exact GH-148 failure mode, now caught instead of silently executed;
- rejects the call, ambiguity-worded (RT-A-006), when MORE than one
  resolution of that kind is on record — regardless of whether the raw value
  happens to equal one of them. A raw value's membership in the union of all
  resolved values of a kind is not proof it is the one meant for THIS call: a
  real, already-resolved value belonging to a different label satisfies plain
  membership just as well as the intended one (e.g. two entities resolved,
  ``ENT_1``/Acme and ``ENT_2``/Beta — supplying ``ENT_2`` where Acme was
  meant used to pass, since ``ENT_2`` really was resolved, just for the wrong
  label). Once ambiguous, the model must disambiguate via
  ``$ref:<kind>:<label>`` (or re-resolve) rather than have a bare raw value
  guessed at — RT-D-001: this rejection (and the sibling multi-match
  ``$ref:<kind>`` rejection) names the kind's own on-record labels directly
  in the error text, since AG-UI never replays the original marker (and its
  label) back into a later run's transcript for the model to learn it from
  any other way;
- passes a raw value through unchanged when no resolution of that kind
  exists yet, or exactly one resolution of that kind exists and the raw
  value matches it.

RT-008: the mismatch rejection above has no escape hatch for a genuinely new,
legitimate raw value (e.g. the user names a fresh id directly) — without one,
the model can get stuck retrying a resolver tool it has no reason to call
until the turn budget is exhausted. Two independent releases:

- the literal token ``$raw:<value>`` on a ``ReuseKind`` field whose operator
  has opted the field into ``allow_raw_override=True`` passes ``<value>``
  through as-is, bypassing the match check for that one call, and is itself
  recorded as a ``ReuseSubstitution`` (``via_raw_override=True``) for the
  caller to audit exactly like a ``$ref`` substitution. RT-002 (GH-148
  follow-up): the rejection error text never names this token — the model
  hallucinating a wrong-but-plausible id is the only adversary this check
  defends against, so the bypass must never be advertised to the caller
  being validated. It is an operator opt-in per field
  (``ReuseKind("entity_id", allow_raw_override=True)``, default ``False``,
  the same shape ``strict`` already uses), not a caller-discoverable escape
  hatch; a field that has not opted in rejects a ``$raw:``-prefixed string
  outright (RT-005) rather than treating it as an ordinary raw value — the
  token means nothing without the opt-in, so letting it fall through to the
  raw-value branch would reach the tool body verbatim whenever no resolution
  of the kind exists yet to catch it by accident via the mismatch check;
- ``ReuseKind("entity_id", strict=False)`` turns off the mismatch rejection
  for that field entirely (substitute-only: ``$ref`` still resolves, a raw
  value is simply never checked against prior resolutions) for a tool whose
  operator has decided the correctness risk doesn't warrant the liveness
  cost.

RT-A-008: both escape hatches above are OPERATOR opt-ins — a field left at
every default (``strict=True``, ``allow_raw_override=False``, the landed
defaults) still had no in-band recovery path for a genuinely new, legitimate
raw value once any resolution of its kind existed: the rejection is
deliberately silent about ``$raw:`` (RT-002), and it doesn't exist by default
anyway, so the model could only loop on the resolver tool until
``max_turns``. ``agent/loop.py`` now tracks consecutive raw-value rejections
per ``(tool_name, field_name, raw value)`` for the lifetime of one
``run_loop`` call (``resolve_reuse_fields``'s ``reject_counts`` parameter,
mutated in place) — after ``MAX_CONSECUTIVE_REUSE_REJECTIONS`` (or the
caller's own ``max_consecutive_rejections``, see below) straight rejections
of the exact SAME raw value on the same field, the next call passes that
value through unchanged instead of rejecting again, and the substitution is
recorded with ``via_forced_passthrough=True`` so the caller can emit a
distinct, auditable ``AuditEvent`` (``reuse_forced_passthrough``) rather than
silence. RT-C-001: the key is scoped to the raw value itself, not merely the
field — a run keyed only on ``(tool_name, field_name)`` (the original shape)
reopens the exact GH-148 failure mode this mechanism exists to catch, since
three DIFFERENT wrong-but-plausible values in a row would exhaust the SAME
budget and the third would be forced through unvalidated; a model that
hallucinates a fresh wrong id on every attempt must keep being rejected
forever, and only a genuinely stuck retry of one identical value earns the
passthrough. RT-B-002: "consecutive raw-value rejections" means BOTH strict
raw-value rejection reasons — the mismatch against a single resolution AND
the ambiguity rejection raised when two or more resolutions of the kind are
on record — since neither leaves the caller an in-band way to supply a
genuinely new value (the ambiguity rejection points at
``$ref:<kind>:<label>``, which RT-A-007 rejects for any label not already on
record). The counter therefore lives at the branch's single rejection
boundary, never inside one reason's own arm. This is unconditional — it
applies regardless of ``strict``/``allow_raw_override``, because it exists
for the field that has NOT opted into either — and, WHEN AN OPERATOR HAS
OPTED IN (see below), trades a bounded window of continued correctness risk
for guaranteed liveness: a persistently wrong value is executed at most once
per stuck retry sequence on that exact value, never rejected forever. RT-005
(GH-148 follow-up): bounded recovery is OFF BY DEFAULT. ``agent/loop.py``
passes ``LoopPolicies.reuse_forced_passthrough_limit`` as
``max_consecutive_rejections`` on every call — including the initial call
that supplies ``reject_counts`` — and that field defaults to ``0``, not
``MAX_CONSECUTIVE_REUSE_REJECTIONS``; ``resolve_reuse_fields`` only grants a
passthrough when ``max_consecutive_rejections > 0``, so on the shipped
default a field left at every default is rejected FOREVER, exactly the
pre-RT-A-008 behavior, even though ``reject_counts`` is supplied and being
tracked. A caller that never passes ``reject_counts`` at all (every call
site that predates RT-A-008) also keeps the old reject-forever behavior
byte-for-byte — the same outcome, reached two different ways. An operator
who wants the liveness fallback opts IN by setting
``LoopPolicies.reuse_forced_passthrough_limit`` to a positive value (e.g.
``MAX_CONSECUTIVE_REUSE_REJECTIONS``, this module's suggested starting
point, not its default). RT-C-001: ``resolve_reuse_fields`` also accepts
``max_consecutive_rejections`` directly for a caller that wants the budget
somewhere other than ``LoopPolicies`` — RT-021: that parameter's own
signature default is ``0``, the same fail-closed value as
``LoopPolicies.reuse_forced_passthrough_limit``, so a caller that supplies
``reject_counts`` but omits ``max_consecutive_rejections`` gets the same
reject-forever behavior rather than silently opting into
``MAX_CONSECUTIVE_REUSE_REJECTIONS``-bounded recovery; such a caller must
pass the constant (or any positive value) explicitly to opt in.

Mirrors ``deferred.py``'s shape: dataclass wrapper here, the unwrap/
substitution mechanism as an ``isinstance``/marker check inline in
``agent/loop.py``.
"""

from __future__ import annotations

import functools
import types
import typing
from dataclasses import dataclass
from typing import Any, Sequence

from pydantic import BaseModel, TypeAdapter
from pydantic_core import to_jsonable_python

_CONTAINER_ORIGINS = frozenset({list, tuple, set, frozenset, dict})

REF_PREFIX = "$ref:"
RAW_PREFIX = "$raw:"
RESOLVED_MARKER_KEY = "__resolved__"

# RT-A-008: bounded-recovery threshold for the OPTED-IN shape. Once an
# operator has opted in (see RT-005 below), a field may be rejected this
# many CONSECUTIVE times for the exact same (tool_name, field_name, raw
# value) triple (RT-C-001 — NOT merely the same (tool_name, field_name)
# pair, which would let a sequence of DIFFERENT hallucinated values exhaust
# the same budget) before the next call for that same value passes through
# instead of rejecting again — see resolve_reuse_fields' `reject_counts`.
#
# RT-005 (GH-148 follow-up): this is a SUGGESTED value for
# `resolve_reuse_fields`'s `max_consecutive_rejections` parameter and for an
# operator's own `LoopPolicies.reuse_forced_passthrough_limit` — it is NOT
# the shipped default. `agent/loop.py`'s `LoopPolicies.
# reuse_forced_passthrough_limit` defaults to 0 (bounded recovery OFF,
# reject-forever), never to this constant: the GH-148 gate this budget lives
# inside of is a correctness gate, and a correctness gate must default
# fail-closed, not fail-open. An operator who wants the liveness fallback
# opts IN per agent by setting `reuse_forced_passthrough_limit` to a
# positive value (this constant is a reasonable starting point); leaving it
# at 0 keeps every ReuseKind field rejecting the same stuck wrong value
# forever.
MAX_CONSECUTIVE_REUSE_REJECTIONS = 2


@dataclass(slots=True)
class Reusable:
    """Returned by a tool to mark its result value as citable in later turns.

    ``value`` — the underlying result, unwrapped and handed to the model
    exactly as if the tool had returned it directly (same semantics as a
    plain ``return``; ``ToolDecl.emits`` matching is checked against this
    unwrapped value, not the wrapper).

    ``kind`` — a short, tool-author-chosen category (e.g. ``"entity_id"``)
    grouping resolutions a later tool call may reference via
    ``$ref:<kind>`` or ``$ref:<kind>:<label>``.

    ``label`` — a human-readable name for this particular resolution (e.g.
    "PT IMC Pelita Logistik"), used to disambiguate multiple resolutions of
    the same ``kind`` and echoed back into the ``__resolved__`` marker.

    RT-011: ``value`` is typically a SCALAR — ``ReuseKind`` only ever
    matches a top-level scalar tool-input field (str/int/float/bool, or any
    other scalar object ``jsonable_reuse_value``/``fold_result_content`` can
    JSON-safe, e.g. ``Enum``/``uuid.UUID``/``Decimal``/``datetime`` —
    RT-002/RT-B-004), so a container or ``BaseModel`` wrapped here can never
    be substituted back into one via ``$ref:<kind>`` — ``resolve_reuse_fields``
    compares a raw argument against ``value`` with a single equality check,
    and the tool's own ``input_model.model_validate`` would reject a
    dict/list argument on a scalar field outright. This is NOT enforced at
    construction time: a tool may legitimately wrap its full structured
    result (a ``dict``, or a ``BaseModel`` also passed to ``emits``) in
    ``Reusable`` purely to participate in the resolved-value/audit machinery
    without ever being ``$ref``-matchable against a ``ReuseKind`` field (see
    ``tests/test_rt002_invoke_any_reusable_unwrap.py``'s
    ``rt002_reusable_with_emits_tool``/``..._dict_tool``) — rejecting that
    shape outright would break this supported pattern. A tool author who
    intends the value to be referenced via ``$ref:<kind>`` should keep it to
    a scalar; wrapping a large dict/``BaseModel`` still duplicates the whole
    result a second time inside ``messages`` (replayed into every subsequent
    ``contextId`` continuation, uncapped), which is the cost to weigh.

    ``None`` IS rejected at construction time: ``resolve_reuse_fields``
    treats an explicit ``None`` argument as "not supplied" and never checks
    it against the index (RT-018), so a ``Reusable(value=None, ...)``
    resolution could never be matched or referenced by any raw value or
    ``$ref`` token — there is no legitimate use for it, unlike the
    dict/``BaseModel`` case above.
    """

    value: Any
    kind: str
    label: str

    def __post_init__(self) -> None:
        if self.value is None:
            raise TypeError(
                "Reusable.value must not be None — a None resolution can "
                "never be matched by a raw value or referenced via $ref "
                "(resolve_reuse_fields treats an explicit None argument as "
                "not supplied)"
            )


@dataclass(slots=True)
class ReuseKind:
    """Input-model field marker: ``Annotated[str, ReuseKind("entity_id")]``.

    Declares that a tool input field accepts either a raw value or a
    ``$ref:<kind>``/``$ref:<kind>:<label>`` token referencing a value a
    prior tool call in this conversation returned wrapped in ``Reusable`` of
    the same ``kind``. ``agent/loop.py`` enforces the match (GH-148) before
    invoking the tool.

    Supports a **top-level scalar field only** — e.g. ``str``, ``int``, or
    ``<scalar> | None``. Two shapes are NOT supported and
    ``reuse_fields_for_model`` raises ``TypeError`` at ``@tools.tool``
    registration time rather than shipping either silently (RT-007):

    - a container field (``Annotated[list[str], ReuseKind("entity_id")]``)
      — ``resolve_reuse_fields`` matches a raw argument against a resolved
      value with a single equality check, which cannot address one element
      inside a list/tuple/set/dict, so a container argument that legitimately
      carries a resolved value (e.g. ``["ENT_1"]`` when ``ENT_1`` IS the
      resolved id) is permanently rejected as a mismatch;
    - ``ReuseKind`` on a field of a *nested* model — ``reuse_fields_for_model``
      and the loop only ever look at ``input_model``'s own top-level fields,
      so the annotation is silently inert and any ``$ref:`` token there
      reaches the tool verbatim, with no substitution and no validation.

    RT-B-004: a non-``str`` scalar (``int``, ``float``, ``bool``, or any of
    those ``| None``) IS supported, but only because
    ``ToolEntry.input_schema(include_reuse_hint=True)`` widens the advertised
    property to also accept a string when it otherwise would not. The
    ``$ref:<kind>`` token is a string sentinel, so a description-only hint on
    a ``{"type": "integer"}`` property is unusable on Bedrock Converse and
    every other provider that constrains tool arguments to the declared
    schema. The widening applies to the model-facing tool schema only — the
    field's own ``input_model`` validation is unchanged, because
    ``resolve_reuse_fields`` replaces the token with the resolved value of
    the real type before ``ToolEntry.invoke`` calls ``model_validate``.

    ``strict`` (RT-008, default ``True``) — when ``False``,
    ``resolve_reuse_fields`` never rejects a raw value on this field for
    failing to match a prior resolution; ``$ref``/``$ref:<label>`` still
    resolve normally. Use for a field where the correctness risk of a
    silently-wrong substitution does not justify blocking every genuinely
    new value the model or user supplies directly.

    ``allow_raw_override`` (RT-002, default ``False``) — when ``True``, the
    per-call ``$raw:<value>`` token (see ``RAW_PREFIX``) bypasses the
    mismatch check for this field, same as before RT-002. This is an
    OPERATOR opt-in, not a caller-discoverable escape hatch: the ordinary
    mismatch-rejection error ``resolve_reuse_fields`` returns for an
    unprefixed raw value never names ``$raw:`` (RT-002), so a model that
    hallucinated a wrong id gets no hint that resubmitting the same value
    with a prefix would execute it. Set this only on a field whose operator
    has accepted that tradeoff; a field left at the default REJECTS a
    ``$raw:``-prefixed string outright (RT-005) rather than treating it as
    an ordinary raw value — since the model has already supplied the token
    itself on that call, naming it back in this specific rejection teaches
    nothing RT-002 is trying to withhold.
    """

    kind: str
    strict: bool = True
    allow_raw_override: bool = False


@dataclass(slots=True)
class ReuseSubstitution:
    """One field whose ``$ref`` token, or ``$raw:`` override token,
    ``agent/loop.py`` replaced with an effective value — carries only
    schema-declared identifiers (field name, kind), never the resolved/raw
    value or label (SI-2), so callers can build an auditable event from it
    safely.

    ``via_raw_override`` (RT-008) — ``True`` when the field's effective value
    came from stripping a ``$raw:<value>`` token rather than resolving a
    ``$ref``; callers use this to phrase the audit note differently (a
    deliberate validation bypass, not a substitution of a known-good value).

    ``via_forced_passthrough`` (RT-A-008) — ``True`` when the field's
    effective value is a raw value that mismatched a prior resolution, but
    was let through unchanged because the caller's ``reject_counts`` showed
    the configured ``max_consecutive_rejections`` (RT-021: fail-closed,
    defaults to ``0`` — ``MAX_CONSECUTIVE_REUSE_REJECTIONS`` is a suggested
    opt-in value, never the default) straight rejections of that exact
    ``(tool_name, field_name, raw value)`` triple already happened (RT-C-001
    — scoped to the specific value, not merely the field, so a sequence of
    DIFFERENT hallucinated values never earns this) — the bounded-recovery
    escape hatch for a field that never opted into ``allow_raw_override`` or
    ``strict=False``. Mutually exclusive with ``via_raw_override``: callers
    should phrase this audit note as an automatic liveness fallback, not an
    operator-authorized bypass."""

    field_name: str
    kind: str
    via_raw_override: bool = False
    via_forced_passthrough: bool = False


def _wire_field_name(field_name: str, field_info: Any) -> str:
    """The PRIMARY key ``model_json_schema()`` advertises for this field —
    pydantic keys ``properties`` by ``validation_alias`` (falling back to
    ``alias``, then the python attribute name) whenever an alias is
    declared, on the field itself or via a model-level ``alias_generator``.
    This is the key ``input_schema``'s reuse-hint injection must use, since
    it edits the SCHEMA's ``properties`` dict, which is always alias-keyed.

    RT-001 (GH-148 follow-up): on a model that has ALSO opted into
    ``populate_by_name=True``/``validate_by_name=True`` (see
    ``_accepts_field_name_alias``), this is NOT the only key
    ``model_validate`` will accept — every ``ReuseKind`` map
    (``reuse_fields_for_model`` and friends) then keys by BOTH this name and
    the bare python ``field_name``, not by this name alone. Earlier
    revisions of this docstring claimed ``model_validate`` "rejects the
    plain field name outright, even with ``populate_by_name=True``" — that
    is false (verified live): ``populate_by_name=True`` makes the model
    accept a call keyed by EITHER the alias or the python attribute name,
    and ``model_validate`` constructs the object successfully either way. A
    model that declares an alias together with ``populate_by_name=True`` is
    exactly the shape most likely to want ``ReuseKind`` (camelCase wire
    fields are common on A2UI-facing tools), so keying only on the alias
    used to silently no-op the entire substitution/validation gate on
    precisely those fields: a tool call keyed by the python field name would
    skip both the ``$ref:``/``$raw:`` substitution and the raw-value
    mismatch check, while ``model_validate`` accepted it without complaint.
    A model that has NOT opted in (the common case, and every existing
    ``ReuseKind`` model predating RT-001) is unaffected: ``model_validate``
    only ever accepts this name for such a model, so keying by it alone
    remains correct and complete — see ``_accepts_field_name_alias``."""
    validation_alias = field_info.validation_alias
    if isinstance(validation_alias, str):
        return validation_alias
    if isinstance(field_info.alias, str):
        return field_info.alias
    return field_name


def _accepts_field_name_alias(input_model: type[BaseModel]) -> bool:
    """True when ``input_model.model_validate`` also accepts the bare python
    field name as an alternate key for an aliased field, alongside the alias
    itself (RT-001).

    Pydantic v2's ``populate_by_name`` config key (superseded by, and
    normalized internally to, ``validate_by_name`` since pydantic 2.11 —
    checking both covers either pydantic version) is what enables this; a
    model that declares neither — including one with only a model-level
    ``alias_generator`` and no explicit opt-in — only ever accepts the alias
    (verified live: an ``alias_generator`` alone does NOT make
    ``model_validate`` accept the bare field name). Gating the second
    ``ReuseKind`` map entry on this, rather than adding it unconditionally
    whenever the alias and field name differ, keeps every pre-RT-001 model
    (the common case: an alias with no ``populate_by_name``) keyed
    exclusively by the alias, exactly as before — only a model that has
    itself opted into accepting both names gains a map entry for the
    second one."""
    config = input_model.model_config
    return bool(config.get("validate_by_name") or config.get("populate_by_name"))


def _strip_optional(annotation: Any) -> Any:
    """Unwrap ``X | None`` / ``Optional[X]`` down to ``X`` so the container/
    nested-model checks below see through the mechanism's common "optional
    field" shape."""
    origin = typing.get_origin(annotation)
    if origin is typing.Union or origin is types.UnionType:
        non_none = [a for a in typing.get_args(annotation) if a is not type(None)]
        if len(non_none) == 1:
            return non_none[0]
    return annotation


def _references_reuse_kind(model: type[BaseModel], _seen: frozenset[type] = frozenset()) -> bool:
    """True when ``model`` declares a ``ReuseKind``-annotated field, directly
    or on any ``BaseModel`` reachable through its own fields (including
    through Optional/list/tuple/set/dict) — the nested-model shape
    ``reuse_fields_for_model`` does not support (RT-007)."""
    if model in _seen:
        return False
    _seen = _seen | {model}
    for field_info in model.model_fields.values():
        if any(isinstance(meta, ReuseKind) for meta in field_info.metadata):
            return True
        base = _strip_optional(field_info.annotation)
        candidates = (
            typing.get_args(base) if typing.get_origin(base) in _CONTAINER_ORIGINS else (base,)
        )
        for candidate in candidates:
            if (
                isinstance(candidate, type)
                and issubclass(candidate, BaseModel)
                and _references_reuse_kind(candidate, _seen)
            ):
                return True
    return False


def _assign_reuse_map_entry(
    result: dict[str, Any],
    owners: dict[str, str],
    key: str,
    field_name: str,
    value: Any,
    input_model: type[BaseModel],
) -> None:
    """Write ``result[key] = value``, raising ``TypeError`` when ``key`` was
    already claimed by a DIFFERENT field (RT-008).

    RT-001's dual-keying (wire name + bare python field name, both mapping
    to the same field's ``kind``/``strict``/``allow_raw_override``/type)
    writes up to two keys per field into one flat map with no collision
    check. A model declaring field ``a`` with ``alias="b"`` alongside a
    REAL field ``b`` produces two writes to key ``"b"`` — one field's
    ``ReuseKind`` policy silently overwrites the other's, and whichever
    field is iterated last wins, applying the WRONG policy to a field
    rather than none. ``owners`` (private to one call of the enclosing
    ``reuse_*_for_model`` function) tracks which field's write currently
    owns each key so a second, DIFFERENT field's write to the same key is
    caught here instead of silently overwriting. Two writes for the SAME
    field (its wire-name entry, then its RT-001 python-name shadow entry,
    or vice versa) are not a collision — ``owners`` records that they agree.
    """
    owner = owners.get(key)
    if owner is not None and owner != field_name:
        raise TypeError(
            f"{input_model.__name__}: ReuseKind fields {owner!r} and "
            f"{field_name!r} both resolve to the wire key {key!r} — declare "
            "a distinct alias for one of them"
        )
    owners[key] = field_name
    result[key] = value


def reuse_fields_for_model(input_model: type[BaseModel] | None) -> dict[str, str]:
    """Map of wire field name -> declared ``kind`` for every top-level scalar
    field on ``input_model`` annotated ``Annotated[<type>,
    ReuseKind("<kind>")]``.

    RT-019 (GH-148 follow-up): keyed on the WIRE name (``_wire_field_name`` —
    the field's alias when one is declared, else the python attribute name).
    ``model_json_schema()`` advertises, and a model call is normally keyed
    by, the alias — so the arguments dict this map is matched against (both
    here in ``resolve_reuse_fields`` and in ``ToolEntry.input_schema``'s
    ``$ref`` hint lookup) is usually keyed by the wire name.

    RT-001 (GH-148 follow-up #2): ALSO keyed on the bare python
    ``field_name`` whenever it differs from the wire name. A model whose
    config declares ``populate_by_name=True``/``validate_by_name=True`` (or,
    on some pydantic versions, an ``alias_generator`` alone) accepts a call
    keyed by EITHER name — see ``_wire_field_name``'s docstring — so keying
    only on the wire name left the python-field-name-keyed call able to skip
    substitution and the mismatch check entirely while still validating
    successfully, the exact GH-148 failure mode this whole module exists to
    close. Both entries map to the same ``kind``; when they collide (no
    alias declared) this is just one entry as before.

    Raises ``TypeError`` at tool-registration time (called from the
    ``@tools.tool`` decorator) for either shape ``ReuseKind`` does not
    support (see its docstring) instead of shipping a silent no-op or a
    permanently-failing tool (RT-007): ``ReuseKind`` on a list/tuple/set/
    dict field, or on a field of a nested ``BaseModel`` (checked
    recursively, including through Optional/list/tuple/set/dict) whether or
    not the outer field carrying that nested model is itself annotated.

    Empty when ``input_model`` is ``None`` or declares no such fields — the
    registry computes this once at tool-declaration time and stores it on
    ``ToolDecl.reuse_fields`` so the loop's fast path (an unaffected tool
    skips the substitution/validation machinery entirely) is a single dict
    truthiness check, not a re-introspection per call.
    """
    if input_model is None:
        return {}
    result: dict[str, str] = {}
    owners: dict[str, str] = {}
    for field_name, field_info in input_model.model_fields.items():
        reuse_kind = next(
            (meta for meta in field_info.metadata if isinstance(meta, ReuseKind)), None
        )
        base = _strip_optional(field_info.annotation)
        if reuse_kind is not None:
            if typing.get_origin(base) in _CONTAINER_ORIGINS or (
                isinstance(base, type) and issubclass(base, BaseModel)
            ):
                raise TypeError(
                    f"{input_model.__name__}.{field_name}: ReuseKind only supports a "
                    "top-level scalar field — a list/tuple/set/dict or nested "
                    "BaseModel field is not supported (see ReuseKind's docstring)"
                )
            wire_name = _wire_field_name(field_name, field_info)
            _assign_reuse_map_entry(
                result, owners, wire_name, field_name, reuse_kind.kind, input_model
            )
            if field_name != wire_name and _accepts_field_name_alias(input_model):
                # RT-001: also cover a call keyed by the bare python
                # attribute name, on a model that has opted into accepting
                # it (see this function's and _wire_field_name's/
                # _accepts_field_name_alias's docstrings).
                _assign_reuse_map_entry(
                    result, owners, field_name, field_name, reuse_kind.kind, input_model
                )
            continue
        candidates = (
            typing.get_args(base) if typing.get_origin(base) in _CONTAINER_ORIGINS else (base,)
        )
        for candidate in candidates:
            if (
                isinstance(candidate, type)
                and issubclass(candidate, BaseModel)
                and _references_reuse_kind(candidate)
            ):
                raise TypeError(
                    f"{input_model.__name__}.{field_name}: ReuseKind on a field of a "
                    "nested model is not supported — it only applies to a top-level "
                    "scalar field of the tool's input_model (see ReuseKind's "
                    "docstring)"
                )
    return result


def reuse_strict_for_model(input_model: type[BaseModel] | None) -> dict[str, bool]:
    """Map of wire field name -> declared ``strict`` (RT-008) for every
    ``ReuseKind`` field ``reuse_fields_for_model`` accepts for
    ``input_model``.

    Mirrors that function's field scan (including its RT-019 wire-name
    keying AND its RT-001 dual (wire name + python field name) keying — see
    both docstrings) without repeating its container/nested-model
    validation — call ``reuse_fields_for_model`` first (the registry always
    does, computing ``ToolDecl.reuse_fields`` before ``ToolDecl.
    reuse_strict``) so an unsupported shape has already raised ``TypeError``
    there. Empty when ``input_model`` is ``None`` or declares no
    ``ReuseKind`` fields, matching ``reuse_fields_for_model``.
    """
    if input_model is None:
        return {}
    result: dict[str, bool] = {}
    owners: dict[str, str] = {}
    for field_name, field_info in input_model.model_fields.items():
        reuse_kind = next(
            (meta for meta in field_info.metadata if isinstance(meta, ReuseKind)), None
        )
        if reuse_kind is not None:
            wire_name = _wire_field_name(field_name, field_info)
            _assign_reuse_map_entry(
                result, owners, wire_name, field_name, reuse_kind.strict, input_model
            )
            if field_name != wire_name and _accepts_field_name_alias(input_model):
                _assign_reuse_map_entry(
                    result, owners, field_name, field_name, reuse_kind.strict, input_model
                )
    return result


def reuse_raw_override_for_model(input_model: type[BaseModel] | None) -> dict[str, bool]:
    """Map of wire field name -> declared ``allow_raw_override`` (RT-002) for
    every ``ReuseKind`` field ``reuse_fields_for_model`` accepts for
    ``input_model``.

    Mirrors ``reuse_strict_for_model``'s shape, field scan, and RT-019/RT-001
    dual (wire name + python field name) keying. Empty when ``input_model``
    is ``None`` or declares no ``ReuseKind`` fields, matching
    ``reuse_fields_for_model``. A field absent from the returned map (or the
    map itself being ``None``) means ``$raw:`` override is NOT permitted on
    that field — the opposite default from ``reuse_strict_for_model``, since
    an operator must opt a field IN to the bypass rather than opt out of
    validation.
    """
    if input_model is None:
        return {}
    result: dict[str, bool] = {}
    owners: dict[str, str] = {}
    for field_name, field_info in input_model.model_fields.items():
        reuse_kind = next(
            (meta for meta in field_info.metadata if isinstance(meta, ReuseKind)), None
        )
        if reuse_kind is not None:
            wire_name = _wire_field_name(field_name, field_info)
            _assign_reuse_map_entry(
                result, owners, wire_name, field_name, reuse_kind.allow_raw_override, input_model
            )
            if field_name != wire_name and _accepts_field_name_alias(input_model):
                _assign_reuse_map_entry(
                    result, owners, field_name, field_name,
                    reuse_kind.allow_raw_override, input_model,
                )
    return result


def reuse_field_types_for_model(input_model: type[BaseModel] | None) -> dict[str, type]:
    """Map of wire field name -> declared (Optional-stripped) scalar type for
    every ``ReuseKind`` field ``reuse_fields_for_model`` accepts for
    ``input_model`` (RT-020).

    Mirrors ``reuse_strict_for_model``'s shape, field scan, and RT-019/RT-001
    dual (wire name + python field name) keying. ``resolve_reuse_fields``
    uses this to coerce a raw argument through the field's own declared type
    — the same coercion ``ToolEntry.invoke``'s later ``input_model.
    model_validate`` would apply — before the match check, so a value
    pydantic would accept as identical (e.g. the string ``"5831"`` against
    an ``int`` field already resolved to ``5831``) is not rejected here,
    before the tool is even reached, as a type mismatch. Empty when
    ``input_model`` is ``None`` or declares no ``ReuseKind`` fields, matching
    ``reuse_fields_for_model``. A field absent from the returned map means
    ``resolve_reuse_fields`` has no declared type to coerce through and
    falls back to the original exact-type-identity check.
    """
    if input_model is None:
        return {}
    result: dict[str, type] = {}
    owners: dict[str, str] = {}
    for field_name, field_info in input_model.model_fields.items():
        reuse_kind = next(
            (meta for meta in field_info.metadata if isinstance(meta, ReuseKind)), None
        )
        if reuse_kind is None:
            continue
        base = _strip_optional(field_info.annotation)
        if isinstance(base, type):
            wire_name = _wire_field_name(field_name, field_info)
            _assign_reuse_map_entry(result, owners, wire_name, field_name, base, input_model)
            if field_name != wire_name and _accepts_field_name_alias(input_model):
                _assign_reuse_map_entry(result, owners, field_name, field_name, base, input_model)
    return result


@functools.lru_cache(maxsize=None)
def _type_adapter_for(field_type: type) -> TypeAdapter:
    """Cached ``TypeAdapter`` per declared ``ReuseKind`` field type (RT-013).

    A field's declared type is fixed at ``@tools.tool`` registration time
    and never changes, but ``_coerce_raw_for_match`` runs on the hot path —
    once per ``ReuseKind`` field, immediately before every matching tool
    call — so building a fresh ``TypeAdapter`` (a full pydantic-core schema
    + validator compile) per call is wasted work. Cached process-wide by
    type rather than threaded through ``ToolDecl``/the registry, since the
    same ``field_type`` object is reused across every call to the same
    field and this needs no per-tool state to be correct.
    """
    return TypeAdapter(field_type)


def _coerce_raw_for_match(raw: Any, field_type: type | None) -> Any:
    """Best-effort coercion of a raw tool-call argument to ``field_type``
    (RT-020) — the same coercion ``ToolEntry.invoke``'s later
    ``input_model.model_validate`` would apply — so ``_raw_matches_resolved``
    compares the value pydantic would actually see, not the model's raw JSON
    argument.

    Returns ``raw`` unchanged whenever coercion is unavailable or unsafe:
    ``field_type`` is unknown, ``raw`` already has exactly that type, or
    coercion fails outright. Never coerces across the ``bool``/``int``
    boundary in either direction — ``bool`` is a ``int`` subclass, so a bare
    ``TypeAdapter(int)`` would happily turn ``True`` into ``1`` and
    ``TypeAdapter(bool)`` would happily turn ``1`` into ``True``, silently
    undoing the RT-014 guard ``_raw_matches_resolved`` enforces (``True``
    must not match a resolved ``1``, nor ``1`` a resolved ``True``) — so
    coercion is skipped, leaving the exact-type-identity check to reject the
    pair as it always has.

    RT-002 (GH-148 follow-up): a successfully coerced value is normalized
    through the SAME ``to_jsonable_python`` conversion ``agent/loop.py``'s
    ``jsonable_reuse_value`` applies to a ``Reusable.value`` before it is
    stored in ``resolved_index`` (RT-005/RT-002). Without this, coercing a
    non-JSON-native ``ReuseKind`` field type — ``Enum``, ``uuid.UUID``,
    ``Decimal``, ``datetime`` (all explicitly supported field types, see
    ``ReuseKind``'s docstring / RT-B-004) — through ``TypeAdapter`` produces
    a live Python object of that type (e.g. a str-``Enum`` member, whose
    ``type()`` is the enum class, not ``str``), while the stored resolved
    value is already JSON-safed (e.g. plain ``str``) from being folded into
    ``messages``. ``_raw_matches_resolved``'s exact-type-identity check then
    rejects the CORRECT value forever, since the two representations never
    compare equal by type. Normalizing the coerced side the same way puts
    both sides of the comparison in the identical representation. A no-op
    for every already-JSON-native coerced value (``str``/``int``/``float``/
    ``bool``), so the RT-020 tests are unaffected.
    """
    if field_type is None or type(raw) is field_type:
        return raw
    if isinstance(raw, bool) or field_type is bool:
        return raw
    try:
        coerced = _type_adapter_for(field_type).validate_python(raw)
    except Exception:
        return raw
    return to_jsonable_python(coerced, exclude_none=True, fallback=str)


def _raw_matches_resolved(raw: Any, value: Any) -> bool:
    """Type-aware equality for the raw-value match: ``bool``/``int`` (and any
    other subtype pair) must not satisfy ``==`` across a type boundary — e.g.
    ``True == 1`` — since this check is the mechanism's only correctness
    gate."""
    return type(raw) is type(value) and raw == value


def index_entry_key(label: str | None, value: Any) -> tuple[str | None, str, str]:
    """Type-aware identity key for one ``(label, value)`` resolved-index
    entry (RT-007).

    Plain tuple equality (``(label, value) == (label, other_value)``) uses
    Python's cross-type numeric ``==``, which conflates ``1``/``True``/
    ``1.0``: a ``Reusable(value=1, ...)`` and a later ``Reusable(value=True,
    ...)`` of the same ``kind`` and ``label`` collapse into a single index
    entry, after which ``_raw_matches_resolved`` — which deliberately
    enforces type identity to stop exactly that conflation at MATCH time —
    can only ever compare against whichever one happened to be indexed
    first. Keying de-duplication on ``(label, type(value).__name__,
    repr(value))`` instead mirrors ``resolve_reuse_fields``'s own
    ``reject_counts`` keying (``repr``, not the bare value, for the
    identical reason) and keeps the two resolutions distinct."""
    return (label, type(value).__name__, repr(value))


def parse_ref(raw: Any) -> tuple[str, str | None] | None:
    """Parse a ``$ref:<kind>`` or ``$ref:<kind>:<label>`` token.

    Returns ``(kind, label)`` — ``label`` is ``None`` for the bare
    ``$ref:<kind>`` form — or ``None`` when ``raw`` is not a ``$ref`` token
    (including a malformed one, e.g. ``"$ref:"`` with no kind)."""
    if not isinstance(raw, str) or not raw.startswith(REF_PREFIX):
        return None
    rest = raw[len(REF_PREFIX) :]
    if not rest:
        return None
    kind, sep, label = rest.partition(":")
    if not kind:
        return None
    return kind, (label if sep else None)


def scan_resolved(
    messages: Sequence[dict[str, Any]],
) -> dict[str, list[tuple[str | None, Any]]]:
    """Rebuild the "resolved this conversation" index by scanning
    ``messages`` for ``__resolved__`` markers folded into tool-result
    content blocks.

    Called once at the start of every ``run_loop`` call, over ``messages``
    plus ``extra_resolved_messages`` when the caller supplied one (RT-A-004).
    This function's own logic does not vary by transport, but what it is
    asked to scan does (module docstring, RT-001/RT-A-004): A2A's
    ``TaskRecord.messages`` is server-persisted and carries a prior turn's
    markers intact, so ``run_loop`` scans it directly; AG-UI's client-resent
    transcript has already been through ``routes/ag_ui.py::_fold_history``,
    which strips every toolResult block, so that route instead passes the
    prior runs' ``TaskStore.context_reusable_messages(thread_id)`` in via
    ``extra_resolved_messages`` for this function to scan on the side.
    Returns ``{kind: [(label, value), ...]}`` in the order
    markers appear in ``messages``, de-duplicated so an identical
    (label, value) pair recorded twice (e.g. a task-local cache hit
    re-folding the same ``Reusable``) contributes one entry, not two —
    otherwise a repeat resolution would spuriously turn a single-match bare
    ``$ref:<kind>`` lookup into an "ambiguous" rejection. RT-007:
    de-duplication is keyed via ``index_entry_key`` (type-aware, not plain
    tuple ``==``) so a ``1`` and a ``True`` resolution of the same label
    never collapse into one entry — see that function's docstring.

    RT-001 (GH-148 follow-up, control-plane isolation): a ``{"json": ...}``
    block is only ever accepted as a genuine marker when
    ``RESOLVED_MARKER_KEY`` is its SOLE top-level key — the exact shape both
    genuine producers build (``agent/loop.py`` and ``runner.py``'s deferred
    awaiter both append ``{"json": {RESOLVED_MARKER_KEY: resolved_marker}}``
    as a block of its own, never merged with a tool's own result keys).
    This is defense-in-depth alongside ``fold_result_content`` stripping the
    key from any tool-returned dict/BaseModel before folding: even a future
    fold path that plants ``__resolved__`` alongside other keys in one block
    is rejected here rather than silently accepted as genuine.
    """
    index: dict[str, list[tuple[str | None, Any]]] = {}
    seen: dict[str, set[tuple[str | None, str, str]]] = {}
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        for block in message.get("content") or []:
            if not isinstance(block, dict):
                continue
            tool_result = block.get("toolResult")
            if not isinstance(tool_result, dict):
                continue
            for item in tool_result.get("content") or []:
                if not isinstance(item, dict):
                    continue
                payload = item.get("json")
                if not isinstance(payload, dict):
                    continue
                if set(payload.keys()) != {RESOLVED_MARKER_KEY}:
                    # RT-001: a genuine marker block never carries any other
                    # key alongside RESOLVED_MARKER_KEY — reject a block
                    # that does rather than risk treating tool-returned data
                    # as a control-plane marker.
                    continue
                marker = payload.get(RESOLVED_MARKER_KEY)
                if not isinstance(marker, dict):
                    continue
                kind = marker.get("kind")
                if not isinstance(kind, str) or not kind:
                    continue
                label = marker.get("label")
                value = marker.get("value")
                key = index_entry_key(label, value)
                seen_keys = seen.setdefault(kind, set())
                if key not in seen_keys:
                    seen_keys.add(key)
                    index.setdefault(kind, []).append((label, value))
    return index


def _is_resolved_marker_item(item: Any) -> bool:
    """The exact ``scan_resolved``/RT-001 acceptance gate for one
    ``toolResult`` content item: a ``{"json": {...}}`` block whose payload's
    SOLE top-level key is ``RESOLVED_MARKER_KEY``. Kept in sync with
    ``scan_resolved``'s own inline check by inspection, not import, since
    ``scan_resolved`` also needs the marker's inner fields afterward and
    this helper only answers "is this a marker at all"."""
    if not isinstance(item, dict):
        return False
    payload = item.get("json")
    return isinstance(payload, dict) and set(payload.keys()) == {RESOLVED_MARKER_KEY}


def extract_resolved_markers(messages: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only the genuine ``__resolved__`` marker content items found
    in ``messages``, dropping everything ``scan_resolved`` never reads —
    full message text, toolUse blocks, and non-marker toolResult content
    (RT-010).

    Used to bound ``InMemoryTaskStore.context_reusable_messages()``'s
    return value to actual marker volume rather than full transcript size:
    that method exists only to seed ``run_loop``'s ``resolved_index`` via
    ``extra_resolved_messages``, and ``scan_resolved`` reads nothing else
    out of it. The output is a drop-in ``scan_resolved`` input —
    pre-filtered, functionally identical to scanning the un-extracted
    originals, just far smaller on a long-lived thread.
    """
    extracted: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        for block in message.get("content") or []:
            if not isinstance(block, dict):
                continue
            tool_result = block.get("toolResult")
            if not isinstance(tool_result, dict):
                continue
            markers = [
                item for item in (tool_result.get("content") or []) if _is_resolved_marker_item(item)
            ]
            if markers:
                extracted.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "toolResult": {
                                    "toolUseId": tool_result.get("toolUseId"),
                                    "content": markers,
                                }
                            }
                        ],
                    }
                )
    return extracted


def _reset_field_reject_counts(
    reject_counts: dict[tuple[str, str, str], int] | None, tool_name: str, field_name: str
) -> None:
    """Clear every tracked rejection count for ``(tool_name, field_name)``,
    regardless of which raw value each entry is keyed on (RT-C-001).

    Called on every success path (a resolved ``$ref``, a ``$raw:`` override,
    a matching raw value, or nothing to check against yet) so budget spent
    rejecting one wrong-but-plausible value earlier in the conversation never
    lingers against a LATER attempt of that same value once the field is
    demonstrably back on track — mirroring the pre-RT-C-001 behavior where a
    success reset the field's entire count, just scoped per-value now rather
    than per-field.
    """
    if reject_counts is None:
        return
    for key in [k for k in reject_counts if k[0] == tool_name and k[1] == field_name]:
        del reject_counts[key]


def _known_labels_hint(resolved_for_kind: list[tuple[str | None, Any]]) -> str:
    """Render the on-record labels for one kind as a rejection-text suffix,
    or ``""`` when none carry a label (RT-D-001 — see ``resolve_reuse_fields``'s
    ``error``-return docstring paragraph for the full rationale).

    Only ever fed the labels already on record for the kind — tool-author-
    supplied display names attached by the ``Reusable(..., label=...)`` that
    resolved them, never a resolved VALUE and never anything the CALLER
    supplied on this rejected call — so this cannot leak the mismatched raw
    value, the resolved value, or a caller-supplied label that matched
    nothing (SI-2 is scoped to those, not to a kind's own label set).
    De-duplicated and sorted so the hint is deterministic regardless of
    resolution order or repeats."""
    labels = sorted({lbl for lbl, _ in resolved_for_kind if lbl})
    if not labels:
        return ""
    return f" (known labels: {', '.join(labels)})"


def resolve_reuse_fields(
    tool_name: str,
    arguments: dict[str, Any],
    fields: dict[str, str],
    index: dict[str, list[tuple[str | None, Any]]],
    strict_fields: dict[str, bool] | None = None,
    raw_override_fields: dict[str, bool] | None = None,
    reject_counts: dict[tuple[str, str, str], int] | None = None,
    field_types: dict[str, type] | None = None,
    max_consecutive_rejections: int = 0,
) -> tuple[dict[str, Any], list[ReuseSubstitution], str | None]:
    """Apply the ``ReuseKind`` substitution/validation contract (GH-148) to
    one tool call's ``arguments``.

    ``strict_fields`` — optional field name -> ``ReuseKind.strict`` map (the
    registry's ``ToolDecl.reuse_strict``, RT-008). A field absent from it, or
    ``strict_fields`` itself being ``None``, is treated as strict (the
    original, pre-RT-008 behavior) — every existing caller that predates the
    ``strict`` flag needs no change.

    ``raw_override_fields`` — optional field name -> ``ReuseKind.
    allow_raw_override`` map (the registry's ``ToolDecl.reuse_raw_override``,
    RT-002). A field absent from it, or ``raw_override_fields`` itself being
    ``None``, is treated as ``False`` — the OPPOSITE default from
    ``strict_fields``, since ``$raw:`` bypassing validation is an operator
    opt-in, not a default caller capability. A ``$raw:``-prefixed string on a
    field not in this map (or with ``raw_override_fields`` itself ``None``)
    is REJECTED outright (RT-005), unconditionally — regardless of ``strict``
    or whether any resolution of the field's kind exists yet — rather than
    falling through to the raw-value branch below, where an empty ``index``
    would otherwise let the literal token reach the tool body verbatim.

    RT-018: an explicit ``None`` argument on a field (the "not supplied" value
    for the ``<scalar> | None`` shape ``ReuseKind``'s docstring documents as
    supported) passes through unchanged and is never treated as a raw value
    to match — it is exempt from both the ``$ref``/``$raw`` parsing above and
    the mismatch check below, regardless of ``strict`` or whether a
    resolution of that kind exists.

    ``reject_counts`` (RT-A-008, RT-C-001) — optional, caller-owned
    ``(tool_name, field_name, repr(raw value)) -> consecutive rejection
    count`` map, mutated in place. When given, EVERY strict raw-value
    rejection below — the mismatch against a single resolution, and the
    RT-A-006 ambiguity rejection raised when two or more resolutions of the
    kind are on record — increments the count for that exact ``(tool_name,
    field_name, raw value)`` triple instead of always returning the error:
    once the count exceeds ``max_consecutive_rejections``, the call passes
    that raw value through unchanged instead of rejecting again, recorded as
    a ``ReuseSubstitution`` with ``via_forced_passthrough=True``, and the
    count for that value resets. RT-C-001: the key is scoped to
    ``repr(raw)``, not merely ``(tool_name, field_name)`` — keying on the
    field alone reopens the exact GH-148 failure mode this mechanism exists
    to catch, since three DIFFERENT wrong-but-plausible values in a row would
    exhaust the SAME budget and the third would be forced through
    unvalidated; only a genuinely stuck retry of the identical value earns
    the passthrough, and a model that hallucinates a fresh wrong id on every
    attempt keeps being rejected. ``repr`` rather than the bare value because
    a dict/tuple key compares by ``==``, which conflates ``1`` and ``True``
    across a type boundary (the same hazard ``_raw_matches_resolved`` guards
    against) — ``repr(1) == "1"`` and ``repr(True) == "True"`` never collide.
    RT-B-002: both rejection reasons are counted at ONE rejection boundary,
    not inside either reason's own arm — an early ``return`` above the
    counter exempts that reason from the bound entirely, and the ambiguity
    reason is the dominant shape (any conversation resolving two values of
    one kind reaches it) with no in-band recovery of its own, since the
    ``$ref:<kind>:<label>`` form it recommends is itself rejected (RT-A-007)
    for a label no resolution carries. A ``$ref``-token rejection is NOT
    counted: those leave the caller a real recovery move (supply the raw
    value, or a label that is on record). Any field that resolves via
    ``$ref``, a ``$raw:`` override, or a matching raw value clears every
    tracked count for that field (``_reset_field_reject_counts``,
    regardless of which value each was keyed on) — the budget guards a stuck
    retry loop on the SAME wrong value, not a running total across the whole
    conversation. ``None`` (every caller that predates RT-A-008) preserves
    the original reject-forever behavior exactly. This bound is
    unconditional — it applies regardless of ``strict``/``allow_raw_override``,
    since it exists precisely for the field that opted into neither.

    ``max_consecutive_rejections`` (RT-C-001, RT-021: default ``0``) — the
    threshold ``reject_counts`` is checked against. Fail-closed by default —
    reject-forever, never a forced passthrough — for the same reason
    ``LoopPolicies.reuse_forced_passthrough_limit`` defaults to ``0``: the
    GH-148 gate this budget lives inside of is a correctness gate, and a
    correctness gate must never default fail-open. ``agent/loop.py`` passes
    ``LoopPolicies.reuse_forced_passthrough_limit`` here; a caller that wants
    the budget somewhere other than ``LoopPolicies`` opts in explicitly by
    passing a positive value directly (e.g. ``MAX_CONSECUTIVE_REUSE_REJECTIONS``,
    this module's suggested starting point, not this parameter's default).
    Meaningless when ``reject_counts`` is ``None``.

    ``field_types`` (RT-020) — optional wire field name -> declared
    (Optional-stripped) scalar type map (the registry's ``ToolDecl.
    reuse_field_types``). ``resolve_reuse_fields`` runs against the model's
    raw, un-validated tool call arguments — before ``ToolEntry.invoke``'s own
    ``input_model.model_validate`` ever sees them — while the match check
    below requires exact type identity, so a correct value supplied in a
    merely coercible form (e.g. the string ``"5831"`` where the field is
    typed ``int`` and already resolved to ``5831``) used to be rejected as a
    mismatch even though pydantic would coerce it to the identical value. A
    field present in ``field_types`` has its raw value coerced through that
    type (mirroring pydantic's own lax coercion, including the RT-014 bool/
    int type-boundary guard — see ``_coerce_raw_for_match``) before the match
    check; a field absent from the map, or ``field_types`` itself being
    ``None``, falls back to the original exact-type-identity check
    unchanged — every caller that predates RT-020 needs no change. Coercion
    only affects the comparison: ``effective_arguments`` still carries the
    raw, uncoerced value, exactly as before — the tool's own
    ``input_model.model_validate`` performs the real coercion.

    Returns ``(effective_arguments, substitutions, error)``:

    - ``effective_arguments`` — a copy of ``arguments`` with any
      ``$ref:<kind>``/``$ref:<kind>:<label>`` token replaced by its resolved
      value, and any ``$raw:<value>`` token on a field with
      ``allow_raw_override=True`` (RT-008/RT-002) replaced by ``<value>``
      verbatim. Never mutates ``arguments`` (the model's original call stays
      intact in the assistant turn already folded into ``messages``).
    - ``substitutions`` — one ``ReuseSubstitution`` per field whose value was
      replaced — a resolved ``$ref``, or a ``$raw:`` override
      (``via_raw_override=True``) — for the caller to emit as an auditable
      event.
    - ``error`` — a generic, SI-2-safe message (schema-declared field name
      and kind only — never the mismatched raw value, the caller-supplied
      label, or any resolved VALUE) when the call must be rejected outright:
      a ``$ref:<kind>:<label>`` whose label matches no resolution (RT-A-007 —
      distinct wording from the ambiguous case below, since the caller
      already supplied a label and disambiguation is not the fix), a
      ``$ref`` that resolves to MORE than one value (the actual ambiguous
      case — tells the caller to add ``<label>``), or — only for a field
      that is ``strict`` — a raw value rejected for one of two reasons
      (RT-A-006): more than one resolution of the kind is on record (a bare
      raw value's membership in that set is not proof it is the one meant for
      THIS call — tells the caller to disambiguate via ``$ref:<kind>:<label>``
      the same way the multi-match ``$ref`` case does, checked BEFORE the
      match itself, so it fires even when the raw value happens to equal one
      of the resolved values), or exactly one resolution exists and the raw
      value does not match it — or, for ANY field regardless of ``strict``,
      a ``$raw:``-prefixed string on a field that has not opted into
      ``allow_raw_override`` (RT-005). The mismatch/ambiguity rejections
      above never name the ``$raw:`` override token (RT-002) — the model
      that just supplied an ordinary wrong raw value is the one adversary
      that check exists to stop, so its own rejection must not teach it the
      bypass; the RT-005 rejection is the one exception, since it only fires
      when the model has already supplied the ``$raw:`` token itself, so
      naming it back teaches nothing new. Callers must not invoke the tool
      when this is set.

      RT-D-001: the two rejections above that recommend ``$ref:<kind>:<label>``
      as the recovery move — the multi-match ``$ref`` case and the raw-value
      ambiguity case — ALSO append the kind's own ON-RECORD labels
      (``_known_labels_hint``): tool-author-supplied display names, never a
      resolved VALUE and never the caller's own (possibly wrong) supplied
      label, so SI-2 is unaffected. Without this the recovery token those two
      rejections name was model-learnable only from a transcript carrying the
      original ``__resolved__`` marker — true on A2A (``TaskRecord.messages``
      replays it verbatim) but never on AG-UI (``routes/ag_ui.py::
      _fold_history`` strips every toolResult block, module docstring), so a
      thread with two AG-UI-resolved values of one kind rejected the CORRECT
      raw value forever with no reachable recovery move at all. Putting the
      labels in the rejection text itself needs no transport-specific carrier
      — the text is this call's own tool result, so every transport delivers
      it back to the model regardless of what a later request replays.
      RT-A-007's own label-mismatch rejection is UNCHANGED: the caller already
      supplied a label there, so echoing the resolved set back teaches it
      nothing a fresh ``$ref:<kind>`` (bare) attempt wouldn't reveal via this
      same hint on its own next rejection.
    """
    effective = dict(arguments)
    substitutions: list[ReuseSubstitution] = []
    # RT-007: every `reject_counts` mutation for a field that "succeeds" (a
    # resolved $ref, a $raw: override, a matching raw value, a forced
    # passthrough, or simply nothing yet to check against) is collected here
    # and applied to `reject_counts` ONLY once every field in `fields` is
    # known not to trigger a hard rejection of the whole call — never as
    # each field is processed. A tool declaring MORE than one ReuseKind
    # field iterates several fields per call; mutating `reject_counts`
    # in place field-by-field let an EARLIER field's forced-passthrough pop
    # (spending its bounded-recovery budget) commit, then a LATER field in
    # the SAME call reject the call outright — discarding the earlier
    # field's earned substitution (the hard rejection below returns a fresh
    # `[]`, not `substitutions`) while its budget was already spent, so the
    # next identical call started that field's counter back at zero and its
    # bounded recovery could never complete for as long as the sibling field
    # kept rejecting. A field's own straight-rejection INCREMENT (the
    # `reject_counts[reject_key] = count` line below, on the branch that
    # immediately `return`s the error for THIS field) is not deferred — that
    # statement's own `return` exits the function right there, so nothing
    # later in this same call can ever discard it.
    pending_field_resets: list[str] = []
    pending_key_pops: list[tuple[str, str, str]] = []
    for field_name, kind in fields.items():
        if field_name not in arguments:
            continue
        raw = arguments[field_name]
        if raw is None:
            continue
        resolved_for_kind = index.get(kind, [])
        # RT-008/RT-002: an explicit, per-call escape hatch — always takes
        # the literal value after the prefix, bypassing both $ref parsing
        # and the mismatch check below, regardless of `strict` — but only on
        # a field whose operator opted it into `allow_raw_override` (RT-002:
        # never advertised to the model, so this must be a deliberate
        # per-field grant, not a default capability every ReuseKind field
        # has). Still recorded as a substitution so the bypass is auditable,
        # not silent.
        raw_override_allowed = (
            raw_override_fields is not None and raw_override_fields.get(field_name, False)
        )
        is_raw_override_token = isinstance(raw, str) and raw.startswith(RAW_PREFIX)
        if is_raw_override_token and not raw_override_allowed:
            # RT-005: a $raw: token is always an escape-hatch attempt, never
            # a candidate raw value — on a field whose operator has NOT
            # opted it into allow_raw_override this must be rejected
            # outright, unconditionally, the same way a malformed $ref token
            # is below, rather than falling through to the raw-value branch
            # where it reaches the tool body verbatim whenever no resolution
            # of the kind exists yet (nothing there would otherwise catch
            # it — the mismatch check only runs when resolved_for_kind is
            # non-empty). Mirrors invoke_any's RT-A-009 parity: the loop is
            # the ONE surface that advertises $ref:<kind> syntax to the model
            # (input_schema(include_reuse_hint=True)), making the sibling
            # $raw: syntax the most likely for a model to try here too.
            return (
                arguments,
                [],
                f"tool {tool_name!r} field {field_name!r} does not accept a "
                f"$raw: override for {kind}; supply the raw value directly",
            )
        if is_raw_override_token:
            effective[field_name] = raw[len(RAW_PREFIX) :]
            substitutions.append(
                ReuseSubstitution(field_name=field_name, kind=kind, via_raw_override=True)
            )
            pending_field_resets.append(field_name)
            continue
        is_ref_token = isinstance(raw, str) and raw.startswith(REF_PREFIX)
        ref = parse_ref(raw)
        if is_ref_token and (ref is None or ref[0] != kind):
            # A $ref-prefixed token is always a reference attempt, never a
            # candidate raw value — malformed (e.g. "$ref:") or naming a
            # different kind must be rejected outright, never fall through
            # to the raw-value branch below and reach the tool body verbatim
            # (RT-006).
            return (
                arguments,
                [],
                f"tool {tool_name!r} field {field_name!r} expects a valid "
                f"$ref:{kind} token; the supplied reference does not "
                "resolve to that kind",
            )
        if ref is not None and ref[0] == kind:
            _, wanted_label = ref
            if not resolved_for_kind:
                return (
                    arguments,
                    [],
                    f"tool {tool_name!r} field {field_name!r} references "
                    f"$ref:{kind} but no {kind} has been resolved yet in "
                    "this conversation",
                )
            if wanted_label is not None:
                matches = [v for lbl, v in resolved_for_kind if lbl == wanted_label]
                if not matches:
                    # RT-A-007: a label WAS supplied and matched nothing — this
                    # is not the ambiguous-match case below, and telling the
                    # caller to disambiguate with a label it already gave
                    # sends it down the wrong recovery path. Never echo the
                    # supplied (or any resolved) label back (SI-2) — the
                    # schema-declared field name and kind are enough to act
                    # on.
                    return (
                        arguments,
                        [],
                        f"tool {tool_name!r} field {field_name!r} — no "
                        f"resolved {kind} carries the supplied label",
                    )
                if len(matches) > 1:
                    # RT-A-02: the caller already supplied a label — the
                    # generic "use $ref:<kind>:<label> to disambiguate"
                    # advice below recommends the exact move it just made,
                    # turning this into a permanent dead end for a label
                    # whose index entries somehow still number more than
                    # one (loop.py's live-index growth now keeps at most one
                    # entry per label within a single run_loop call, but a
                    # scan_resolved rebuild over persisted messages spanning
                    # more than one call/continuation can still surface a
                    # stale duplicate). `wanted_label` is safe to echo here —
                    # unlike the no-match branch above, reaching this branch
                    # already proves it names a real, on-record label
                    # (tool-author-supplied, not arbitrary caller text), so
                    # SI-2 does not bar it. Echo the form of the token
                    # actually supplied ($ref:<kind>:<label>, not the bare
                    # $ref:<kind> the generic branch below prints.
                    return (
                        arguments,
                        [],
                        f"tool {tool_name!r} field {field_name!r} — "
                        f"$ref:{kind}:{wanted_label} still does not resolve "
                        f"to exactly one value; re-resolve {kind} "
                        f"{wanted_label!r} again, or supply the raw value "
                        "directly",
                    )
            else:
                matches = [v for _lbl, v in resolved_for_kind]
                if len(matches) > 1:
                    return (
                        arguments,
                        [],
                        f"tool {tool_name!r} field {field_name!r} — $ref:{kind} "
                        "does not resolve to exactly one value"
                        f"{_known_labels_hint(resolved_for_kind)}; use "
                        f"$ref:{kind}:<label> to disambiguate",
                    )
            effective[field_name] = matches[0]
            substitutions.append(ReuseSubstitution(field_name=field_name, kind=kind))
            pending_field_resets.append(field_name)
        elif resolved_for_kind and (strict_fields is None or strict_fields.get(field_name, True)):
            # RT-B-002: decide the rejection REASON first, then apply the
            # bounded-recovery gate once, at the branch's single rejection
            # boundary. Both strict raw-value rejections below are terminal
            # for the model — neither has an in-band recovery path a caller
            # supplying a genuinely new value could take (the ambiguity
            # rejection sends it to $ref:<kind>:<label>, which RT-A-007
            # rejects for any label not already on record) — so both must be
            # bounded, not just the second one. An early `return` above the
            # counter exempted the ambiguity case entirely, which is the
            # COMMON shape: any conversation that resolves two entities of
            # one kind reaches it, and reject_counts then stayed empty while
            # the field rejected forever.
            reject_reason: str | None = None
            if len(resolved_for_kind) > 1:
                # RT-A-006: with more than one resolution of this kind on
                # record, membership in the union of their values is not
                # proof the raw value is the one actually meant — a real,
                # already-resolved value for a DIFFERENT label would satisfy
                # that check just as well as the intended one. Fail closed
                # rather than guess: send the model to $ref:<kind>:<label>,
                # the one path that names which resolution it means. RT-D-001:
                # name the on-record labels themselves — the recovery move
                # this text recommends is otherwise unreachable on a
                # transport (AG-UI) whose transcript never carries the
                # original marker back to the model.
                reject_reason = (
                    f"tool {tool_name!r} field {field_name!r} value is "
                    f"ambiguous: more than one {kind} has been resolved in "
                    f"this conversation{_known_labels_hint(resolved_for_kind)}; "
                    f"reference it via $ref:{kind}:<label>"
                )
            elif not _raw_matches_resolved(
                _coerce_raw_for_match(
                    raw, (field_types or {}).get(field_name)
                ),
                resolved_for_kind[0][1],
            ):
                reject_reason = (
                    f"tool {tool_name!r} field {field_name!r} value does not "
                    f"match a previously resolved {kind}; re-resolve it, or "
                    f"reference it via $ref:{kind}"
                )
            if reject_reason is not None:
                # RT-A-008: bounded recovery for a field on every default
                # (strict=True, allow_raw_override=False) — no escape hatch
                # otherwise exists for a genuinely new raw value, and neither
                # rejection above names $raw: (RT-002), so without this the
                # model can only loop on a resolver tool until max_turns.
                if reject_counts is not None and max_consecutive_rejections > 0:
                    # RT-C-001: keyed on repr(raw), not just (tool_name,
                    # field_name) — otherwise three DIFFERENT hallucinated
                    # values in a row exhaust one shared budget and the third
                    # is forced through unvalidated, reopening GH-148.
                    reject_key = (tool_name, field_name, repr(raw))
                    count = reject_counts.get(reject_key, 0) + 1
                    if count > max_consecutive_rejections:
                        # RT-007: NOT popped here — deferred until this
                        # whole call is confirmed to succeed (see the
                        # comment above the loop). Popping immediately and
                        # then `continue`-ing risked a LATER field in this
                        # same call rejecting the call outright, discarding
                        # this field's earned substitution while its budget
                        # was already spent.
                        pending_key_pops.append(reject_key)
                        substitutions.append(
                            ReuseSubstitution(
                                field_name=field_name,
                                kind=kind,
                                via_forced_passthrough=True,
                            )
                        )
                        continue
                    reject_counts[reject_key] = count
                return (arguments, [], reject_reason)
            pending_field_resets.append(field_name)
        elif reject_counts is not None:
            pending_field_resets.append(field_name)
    # RT-007: every field in `fields` was processed without triggering a
    # hard rejection of the call — commit the deferred reject_counts
    # mutations now, not before.
    for field_name in pending_field_resets:
        _reset_field_reject_counts(reject_counts, tool_name, field_name)
    if reject_counts is not None:
        for reject_key in pending_key_pops:
            reject_counts.pop(reject_key, None)
    return effective, substitutions, None
