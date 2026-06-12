"""agent_sdk.contrib — EXPERIMENTAL extensions (DESIGN.md §9).

Modules: ``action_gate`` (confirmed execution of side-effecting tools),
``obo`` (on-behalf-of token exchange), ``commitments`` (durable scheduled
actions), and ``webhooks`` (inbound subscriptions). They remain EXPERIMENTAL
(may change in minor releases, with CHANGELOG notice) until the m365 port
validates them — generalized from m365 with no second consumer yet, they are
excluded from the SemVer promise (DESIGN.md §4.0, §9).

Shipped so far: ``action_gate``, ``obo``, and ``commitments``. The rest are not
yet implemented; importing an unshipped module raises ModuleNotFoundError — that
is intentional, there are no silent stubs.
"""
