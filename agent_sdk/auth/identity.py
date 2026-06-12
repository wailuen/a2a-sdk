"""Resolved caller identity — kind-tagged (DESIGN.md §5.5/§6).

``kind`` drives surface assertions (oauth rejected on /admin/*, /oauth/authorize,
key management); ``(kind, subject)`` is the task identity-binding key (§5.1).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Identity:
    kind: str  # "api_key" | "oauth" | "bootstrap"
    subject: str  # key id / token subject
    admin: bool = False
    label: str | None = None

    @property
    def binding(self) -> tuple[str, str]:
        return (self.kind, self.subject)
