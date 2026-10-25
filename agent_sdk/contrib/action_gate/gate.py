"""Confirmation gate primitives.

``confirmation_required(...)`` builds a ``ToolInterrupt`` whose ``resume_handler``
parses the user's response and runs the side effect ONLY on an unambiguous
approval. The parser is transport-agnostic: A2A delivers the resume value as a
plain string (the user's message text), AG-UI delivers a dict
``{"status": ..., "payload": ...}``. Both are normalized by :func:`parse_decision`.

Security posture — **default-deny**. Only an exact, unambiguous affirmative
("yes", "confirm", "approve", …) yields ``Outcome.APPROVED``. A free-text reply
that merely *contains* "yes" ("yes but not to bob") is ``UNCLEAR`` and does NOT
execute — the model re-proposes. This is intentionally stricter than the m365
gate (which treated ambiguous text as a reschedule): a gate guarding side
effects must fail safe. The user's response text is never logged.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Awaitable, Callable

from ...agent.loop import ToolInterrupt

# Exact-match vocabularies (after normalization). Kept deliberately small and
# unambiguous — a gate must not guess. Unknown tokens fall through to UNCLEAR.
_AFFIRMATIVE = frozenset(
    {"yes", "y", "confirm", "confirmed", "ok", "okay", "approve", "approved",
     "proceed", "accept", "accepted", "go", "yep", "yeah"}
)
_NEGATIVE = frozenset(
    {"no", "n", "cancel", "cancelled", "canceled", "stop", "abort", "reject",
     "rejected", "decline", "declined", "deny", "denied", "nope"}
)

# Default response schema surfaced to the client. Per AG-UI, an interrupt's
# responseSchema describes the *payload* a renderer collects (the envelope
# fields interruptId/status are protocol-owned, not form fields). So it
# describes a `decision` the client puts in `payload`. Left open (no
# additionalProperties:false) so a client may attach a free-text note too.
#
# NOTE: responseSchema is an SDK/AG-UI convention carried in the A2A
# input-required status message metadata — a plain A2A client that reads only
# spec fields will ignore it and simply reply with text (which the gate also
# accepts; see parse_decision).
DEFAULT_CONFIRM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "decision": {
            "type": "string",
            "enum": ["approved", "rejected"],
            "description": "approved to perform the proposed action, rejected to cancel it",
        }
    },
    "required": ["decision"],
}


class Outcome(str, Enum):
    """How a resume value was classified. Only ``APPROVED`` executes."""

    APPROVED = "approved"
    REJECTED = "rejected"
    UNCLEAR = "unclear"  # neither an explicit yes nor no — default-deny, never executes


@dataclass(frozen=True)
class Decision:
    """Normalized confirmation outcome handed to the on_* callbacks.

    ``text`` is the user's free-text reply (A2A) when present; it is part of the
    conversation and may be inspected by the callback, but is never logged or
    echoed by this module. WARNING to callbacks: if you return ``decision.text``
    (or ``decision.payload``) from your on_* handler, it becomes the tool result
    fed back to the model — the gate cannot scrub it for you. ``payload`` is the
    structured AG-UI payload (or ``None``).
    """

    outcome: Outcome
    text: str | None = None
    payload: dict[str, Any] | None = None

    @property
    def approved(self) -> bool:
        return self.outcome is Outcome.APPROVED

    @property
    def rejected(self) -> bool:
        return self.outcome is Outcome.REJECTED


ResumeHandler = Callable[[Decision], Awaitable[Any]]


def _classify(token: str) -> Outcome:
    """Exact-match a single normalized token against the yes/no vocab.

    Normalization is ``strip().lower().rstrip(".!? ,")`` — the rstrip argument
    is a CHARACTER SET (trailing punctuation/space), not a suffix. Invariant:
    no vocab token may contain ``.``, ``!``, ``?``, ``,`` or a space, or the
    rstrip could shift its membership. Keep the two sets disjoint.
    """
    t = token.strip().lower().rstrip(".!? ,")
    if t in _AFFIRMATIVE:
        return Outcome.APPROVED
    if t in _NEGATIVE:
        return Outcome.REJECTED
    return Outcome.UNCLEAR


def _merge(signals: list[Outcome]) -> Outcome:
    """Combine independent approve/reject signals, REJECT-WINS (default-deny):
    an explicit reject anywhere overrides an approve (so a contradictory
    ``cancelled`` + ``approved`` denies); an approve needs no contradicting
    reject; absence of any clear signal stays UNCLEAR."""
    if Outcome.REJECTED in signals:
        return Outcome.REJECTED
    if Outcome.APPROVED in signals:
        return Outcome.APPROVED
    return Outcome.UNCLEAR


def parse_decision(resume_value: Any) -> Decision:
    """Normalize a transport-specific resume value into a :class:`Decision`.

    - **A2A** → the resume value is a plain string (the user's message text;
      the route extracts ``TextPart`` text only, so a resume carrying only a
      ``DataPart``/``FilePart`` arrives as ``""`` → UNCLEAR). Classify exact-
      match: a reply that merely *contains* "yes" ⇒ UNCLEAR, never approved.
    - **AG-UI** → a dict ``{"status": ..., "payload": ...}``. The decision is
      canonical: ``status`` is the protocol literal ``resolved``/``cancelled``
      and the human decision is ``payload.decision``. The route rejects any
      other AG-UI ``status``; the gate still classifies a decision-word
      ``status`` (defence in depth). Both are classified and merged
      REJECT-WINS, so a contradictory pair denies.
      ``payload.status`` is NEVER read as a decision (blocks nested-status
      injection).
    - anything else (``None``, list, number, dict without status/payload) →
      ``UNCLEAR`` (default-deny).
    """
    if isinstance(resume_value, dict) and ("status" in resume_value or "payload" in resume_value):
        raw_payload = resume_value.get("payload")
        payload = raw_payload if isinstance(raw_payload, dict) else None
        signals: list[Outcome] = []
        status = resume_value.get("status")
        if status is not None:
            # 'cancelled'/'rejected' → REJECTED; a decision word → its outcome;
            # 'resolved'/unknown → UNCLEAR (handled by the vocab).
            signals.append(_classify(str(status)))
        if payload is not None and payload.get("decision") is not None:
            signals.append(_classify(str(payload["decision"])))
        return Decision(outcome=_merge(signals), text=None, payload=payload)
    if isinstance(resume_value, str):
        return Decision(outcome=_classify(resume_value), text=resume_value, payload=None)
    return Decision(outcome=Outcome.UNCLEAR, text=None, payload=None)


def declined_result(decision: Decision) -> dict[str, Any]:
    """Safe tool result for a non-approved decision — no side effect ran.

    Fed back to the model so it can tell the user nothing was done (and, on
    ``UNCLEAR``, re-propose). Carries no user-supplied text (avoids echoing)."""
    return {"confirmed": False, "outcome": decision.outcome.value}


def confirmation_required(
    *,
    summary: str,
    on_confirm: ResumeHandler,
    on_reject: ResumeHandler | None = None,
    on_unclear: ResumeHandler | None = None,
    response_schema: dict[str, Any] | None = None,
    reason: str = "confirmation",
) -> ToolInterrupt:
    """Build a ``ToolInterrupt`` that gates ``on_confirm`` behind an approval.

    ``raise confirmation_required(...)`` from inside a tool. The loop pauses the
    task in ``input-required``, surfaces ``summary`` (+ ``response_schema``) as
    the proposal, and on resume runs exactly one of:

    - ``on_confirm(decision)`` — only when the reply parses to ``APPROVED``;
    - ``on_unclear(decision)`` — when ``UNCLEAR`` and a handler is given (else
      falls through to reject);
    - ``on_reject(decision)`` — when ``REJECTED`` (or ``UNCLEAR`` with no
      ``on_unclear``); defaults to :func:`declined_result` when omitted.

    The return value of whichever handler runs becomes the tool result (and is
    emitted as an artifact if the tool declares a matching ``emits`` type).

    ``reason`` must NOT contain ``"auth"`` (substring check) — that token routes
    to ``auth-required`` in the runner, a different lifecycle state than a user
    confirmation (``input-required``). If you genuinely need secondary
    credentials, raise ``ToolInterrupt(reason="auth", ...)`` directly instead.

    Re-proposal caution: if ``on_unclear`` itself raises ``confirmation_required``
    to ask again, each nested proposal consumes one interrupt slot in the task
    store; exceeding the store's interrupt cap converts the interrupt into a task
    failure. Do not build unbounded re-proposal loops.
    """
    if not summary or not summary.strip():
        raise ValueError("summary must be a non-empty human-readable proposal")
    if "auth" in reason.lower():
        raise ValueError(
            "reason must not contain 'auth' — that maps to auth-required, not a "
            "user confirmation (input-required)"
        )

    async def _resume(resume_value: Any) -> Any:
        decision = parse_decision(resume_value)
        if decision.outcome is Outcome.APPROVED:
            return await on_confirm(decision)
        if decision.outcome is Outcome.UNCLEAR and on_unclear is not None:
            return await on_unclear(decision)
        if on_reject is not None:
            return await on_reject(decision)
        return declined_result(decision)

    return ToolInterrupt(
        reason=reason,
        message=summary,
        response_schema=response_schema or DEFAULT_CONFIRM_SCHEMA,
        resume_handler=_resume,
    )
