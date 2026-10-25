"""Media type matching shared by every transport (C-079)."""

from __future__ import annotations

from collections.abc import Collection, Sequence

_A2UI_MEDIA_TYPE = "application/a2ui+json"


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


def accepts_a2ui_mode(modes: Sequence[str] | None) -> bool:
    """Whether a request's ``acceptedOutputModes`` allows A2UI output (C-097):
    absent or empty accepts everything; otherwise some mode must match
    ``application/a2ui+json``. The one compare behind both the A2UI build
    decision and the ``X-A2A-Extensions`` echo."""
    if not modes:
        return True
    return any(media_type_match(m, {_A2UI_MEDIA_TYPE}) for m in modes)
