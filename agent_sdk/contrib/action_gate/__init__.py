"""action_gate — confirmed execution of side-effecting tools (DESIGN.md §9).

EXPERIMENTAL (DESIGN.md §4.0): provisional until the m365 port validates it;
may change in minor releases with a CHANGELOG notice.

A side-effecting tool should not act until the human has confirmed. This
module is a thin, *safe* layer over the SDK's first-class interrupt/resume
machinery (``ToolInterrupt`` + the task store's resume channel) — it does NOT
re-implement a pending-action store; the task store already owns interrupt
state, TTL, identity-binding and the resume channel.

Pattern — split *propose* from *execute* so the side effect can ONLY run on
an explicit approval::

    from agent_sdk.contrib.action_gate import confirmation_required

    @tools.tool(tier=2)
    async def send_email(inp: SendInput, *, graph: GraphSource) -> dict:
        async def _execute(decision):                 # runs ONLY if approved
            return await graph.send(inp.to, inp.subject, inp.body)

        raise confirmation_required(
            summary=f"Send email to {inp.to} — subject {inp.subject!r}?",
            on_confirm=_execute,
        )

The proposal is carried as the interrupt *message* (human-readable, surfaced
as the A2A ``input-required`` status text and the AG-UI interrupt outcome) plus
``response_schema`` (an SDK/AG-UI convention describing the expected response,
surfaced in the A2A status message metadata — a plain A2A client ignores it and
just replies with text). The side effect lives inside ``on_confirm`` and is
invoked only when the resume value parses to an unambiguous approval —
**default-deny**: anything that is not a clear yes never executes (see
:func:`parse_decision`).

Resume transport notes (the SDK enforces these; tool authors just need to know):
- The confirmation must come from the SAME authenticated identity as the
  original task submitter — the task store looks up by ``(task_id, identity)``,
  so a different caller gets task-not-found, not a 403.
- AG-UI sends the decision in the ``status`` field (this SDK's core convention)
  or in ``payload.decision`` (canonical AG-UI); the gate accepts both.
- If the interrupted task's TTL expires before the user replies, the resume is
  rejected as task-not-found (a delayed confirmation can therefore fail even
  though the proposal was shown).

This generalizes the m365 ``ActionGate`` (an explicit gate object, not a
decorator flag) onto the SDK interrupt seam.
"""

from __future__ import annotations

from .gate import (
    DEFAULT_CONFIRM_SCHEMA,
    Decision,
    Outcome,
    confirmation_required,
    declined_result,
    parse_decision,
)

__all__ = [
    "confirmation_required",
    "parse_decision",
    "declined_result",
    "Decision",
    "Outcome",
    "DEFAULT_CONFIRM_SCHEMA",
]
