"""Input validators shared by routes, tools, and the @tool machinery."""

from __future__ import annotations

import re
from urllib.parse import quote

from ..models.errors import AgentError, ErrorCategory

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
# conservative: path segments may not contain separators, dots-only names,
# or anything that survives as a traversal/SSRF pivot after quoting
_SEGMENT_FORBIDDEN = re.compile(r"[/\\?#@\s]")


def strip_control_chars(value: str) -> str:
    return _CONTROL_CHARS.sub("", value)


def safe_id(value: str, *, what: str = "id") -> str:
    """Opaque identifiers (task ids, key ids, interrupt ids)."""
    if not _SAFE_ID.fullmatch(value):
        raise AgentError(ErrorCategory.VALIDATION, f"invalid {what}")
    return value


def url_segment(value: str, *, what: str = "value") -> str:
    """Validate-and-quote a string destined for URL path interpolation
    (DESIGN.md §4.2). Call this inside a ``SourceAdapter`` method before
    interpolating any user-derived value into a URL path — the ``@tool``
    layer does NOT auto-sanitize path params, so the adapter is the
    enforcement point.

    Refuses separators, traversal, whitespace and control chars outright,
    then percent-encodes the survivor. Never silently rewrites meaning.
    """
    if not value or len(value) > 512:
        raise AgentError(ErrorCategory.VALIDATION, f"invalid {what}: empty or too long")
    if _CONTROL_CHARS.search(value) or _SEGMENT_FORBIDDEN.search(value):
        raise AgentError(
            ErrorCategory.VALIDATION,
            f"invalid {what}: contains URL-unsafe characters",
        )
    if value in (".", ".."):
        raise AgentError(ErrorCategory.VALIDATION, f"invalid {what}")
    return quote(value, safe="")
