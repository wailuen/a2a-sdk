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
    # Signed-in end user behind an OAuth client (GH-152); None keeps every key
    # byte-identical to a userless identity.
    user: str | None = None

    @property
    def binding(self) -> tuple[str, str]:
        if self.user is None:
            return (self.kind, self.subject)
        return (self.kind, f"{self.subject}|{self.user}")

    @property
    def principal_key(self) -> str:
        kind, subject = self.binding
        return f"{kind}:{subject}"
