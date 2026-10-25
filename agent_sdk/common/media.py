"""Media type matching shared by every transport (C-079)."""

from __future__ import annotations

from collections.abc import Collection


def normalize_media_type(value: str) -> str:
    """Lowercase, drop parameters, and map the legacy ``text`` alias to ``text/plain``."""
    token = value.split(";", 1)[0].strip().lower()
    return "text/plain" if token == "text" else token


def media_type_match(mode: str, supported: Collection[str]) -> bool:
    """Whether ``mode`` (which may be ``*/*`` or ``type/*``) matches any member of ``supported``."""
    token = normalize_media_type(mode)
    normalized = {normalize_media_type(s) for s in supported}
    if token == "*/*":
        return True
    if token.endswith("/*"):
        prefix = token[:-1]
        return any(m.startswith(prefix) for m in normalized)
    return token in normalized
