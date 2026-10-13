"""Log redaction — secrets never reach logs or error payloads (§6)."""

from __future__ import annotations

import re
import traceback
from typing import Any

_SECRET_KEY = re.compile(
    r"(secret|token|password|api[_-]?key|authorization|credential|assertion|"
    r"master[_-]?key|refresh|bearer)",
    re.IGNORECASE,
)
_BEARER_VALUE = re.compile(r"(?i)\b(bearer)\s+\S+")

REDACTED = "[redacted]"

# SI-2: map every Unicode control char to a space — C0 (0x00-0x1F), DEL
# (0x7F) and C1 (0x80-0x9F). C1 is not optional: NEL (0x85) is treated as a
# line break by many log/terminal consumers and CSI (0x9B) is a single-byte
# ANSI escape introducer equivalent to ESC '[', so leaving 0x7F/C1 through
# would defeat the very log/terminal-injection guard this helper exists for.
_CONTROL_CHAR_MAP = dict.fromkeys([*range(0x20), 0x7F, *range(0x80, 0xA0)], " ")


def sanitize_text(s: str, *, max_len: int | None = 64) -> str:
    """Strip control chars and cap length before untrusted (caller-/model-/
    tool-supplied) text reaches a log line or the wire (SI-2). C-007.

    ``max_len=None`` preserves the full untrusted length (a slice stop of
    ``None`` is a no-op) — used by :func:`safe_cell_text`/:func:`safe_block_text`
    below, whose own contract is "cap by caller, not by this step"."""
    return s[:max_len].translate(_CONTROL_CHAR_MAP)


# RT-003: ``origin/main``'s independent lineage registered a SEPARATE C-007
# sibling under the name ``safe_error_text`` — not a rename of the function
# above, a distinct contract: the wider ``_CONTROL_CHARS`` span (every
# ``str.splitlines()`` break char, C0/DEL/C1 and U+2028/U+2029 — see that
# constant below) plus a trailing ``.strip()``, pinned verbatim by
# ``tests/test_redact.py`` (ported unchanged from ``origin/main``) and relied
# on by :func:`safe_cell_text`/:func:`safe_block_text` below. Aliasing it to
# ``sanitize_text`` above would silently narrow it back to the C0/DEL/C1-only
# span and drop the strip, un-fixing exactly what RT-003/GH-130 fixed —
# despite letting an upstream-authored ``from ..common.redact import
# safe_error_text`` resolve. Kept as its own function instead.
def safe_error_text(value: str, *, max_len: int | None = 64) -> str:
    """Strip Unicode control/line-break characters and cap length before an
    untrusted (model-/caller-supplied) string reaches a log line, error
    message, or wire payload (SI-2). Pass ``max_len=None`` to preserve the
    untrusted value's full length for callers where truncation is not part
    of the contract (e.g. table-cell sanitisation)."""
    text = value if max_len is None else value[:max_len]
    return text.translate(_CONTROL_CHARS).strip()


def redact_value(text: str) -> str:
    return _BEARER_VALUE.sub(r"\1 " + REDACTED, text)


def frame_locations(exc: BaseException, *, limit: int = 5) -> str:
    """Format the last ``limit`` traceback frame locations as ``file:line``
    for a diagnostic log line (SI-2). Ported verbatim from ``origin/main``
    (RT-003 C-007 reconciliation) — only ``FrameSummary.filename``/``.lineno``
    are used, never ``.line``, which echoes source text that could itself
    embed a caller-derived literal.

    Not yet wired into any local dispatch catch-all (that is
    ``origin/main``'s GH-129-era LRN-044 work, still ahead of this lineage);
    exported here so the eventual merge finds this symbol already defined,
    not colliding."""
    return "|".join(
        f"{frame.filename}:{frame.lineno}"
        for frame in traceback.extract_tb(exc.__traceback__)[-limit:]
    )


# ── GH-130 structural-separator neutralisation (RT-002, ported from
# origin/main) ──────────────────────────────────────────────────────────
#
# Every char ``str.splitlines()`` treats as a line break (\n \r \v \f \x1c
# \x1d \x1e \x85 U+2028 U+2029) falls inside these three spans, along with
# the rest of C0, DEL and C1. Kept as its OWN constant rather than folded
# into ``_CONTROL_CHAR_MAP`` above: that map is C-007's stable contract for
# ``sanitize_text``'s existing callers (agent/loop.py, models/content_types.py,
# byte-matched by the console JS mirror) and must not silently widen under
# them. This wider span is scoped to the cell/block helpers below, whose
# contract — collapsing every line-break-shaped character, not just C0/DEL/C1
# — is different from sanitize_text's.
_CONTROL_CHARS = dict.fromkeys(
    [*range(0x20), 0x7F, *range(0x80, 0xA0), 0x2028, 0x2029], " "
)

# The block variant of the same span set, for payloads whose contract is
# MULTI-LINE text (markdown documents) rather than a single-line delimited
# cell. ``\n`` and ``\t`` are legitimate CONTENT there, not structure, so
# they survive; every other C0/DEL/C1 char — crucially ESC (0x1B) and CSI
# (0x9B), the terminal-injection introducers, plus NEL (0x85) and
# U+2028/U+2029 — still collapses to a space. ``\r`` is excluded from this
# map and normalised to ``\n`` before translation (a bare CR rewrites the
# current terminal line, the classic log-injection trick, and CRLF must not
# become a double break).
_BLOCK_CONTROL_CHARS = {
    cp: " "
    for cp in [*range(0x20), 0x7F, *range(0x80, 0xA0), 0x2028, 0x2029]
    if cp not in (0x09, 0x0A, 0x0D)
}

# Separators inserted in BARE form, with no surrounding space: "k=v",
# "name<email>", "(type)", "[unread]", and the " | " column join (bare-
# neutralised too — it has no legitimate compact use in a cell).
_BARE_SEPARATORS = str.maketrans({
    "|": "/",
    "│": "/",  # BOX DRAWINGS LIGHT VERTICAL
    "｜": "/",  # FULLWIDTH VERTICAL LINE
    "<": "＜",  # FULLWIDTH LESS-THAN SIGN
    ">": "＞",  # FULLWIDTH GREATER-THAN SIGN
    "(": "（",  # FULLWIDTH LEFT PARENTHESIS
    ")": "）",  # FULLWIDTH RIGHT PARENTHESIS
    "[": "［",  # FULLWIDTH LEFT SQUARE BRACKET
    "]": "］",  # FULLWIDTH RIGHT SQUARE BRACKET
    "=": "＝",  # FULLWIDTH EQUALS SIGN
})

# ",", ":", "–", "—", "→" — their only legitimate compact use is a NUMERIC
# literal, range, or timestamp: "1,234" (thousands), "09:30" (time-of-day),
# "20–30"/"9–5" (a range), "5→10" (a delta). An occurrence flanked by an
# ASCII digit on BOTH sides is left alone; every other compact occurrence —
# flanked by a letter, punctuation, or a string boundary — fabricates a
# delimiter and is neutralised regardless of adjacent whitespace.
_DIGIT_FLANK_EXEMPT = frozenset({",", ":", "–", "—", "→"})
_SPACED_SEPARATOR_DIGIT_RE = re.compile(
    r"(?<!\d)[{c}]|[{c}](?!\d)".format(c="".join(_DIGIT_FLANK_EXEMPT))
)

# "@" is a deliberately ACCEPTED residual: its overwhelmingly common compact
# use is a real email address (flanked by LETTERS, not digits), so only the
# SPACED " @ " joiner form is neutralised — a hostile compact "@" smuggled
# into a non-email field is a knowingly open, narrower gap this value-level
# helper cannot close without per-field type information.
_SPACED_SEPARATOR_AT_RE = re.compile(r"(?<![^\s])[@]|[@](?![^\s])")

_SPACED_SEPARATORS = {
    ":": "：",  # FULLWIDTH COLON
    ",": "，",  # FULLWIDTH COMMA
    "@": "＠",  # FULLWIDTH COMMERCIAL AT
    "–": "-",  # EN DASH → HYPHEN-MINUS
    "—": "-",  # EM DASH → HYPHEN-MINUS
    "→": "⇒",  # RIGHTWARDS ARROW → RIGHTWARDS DOUBLE ARROW
}

# Union of both, for callers that need the full separator alphabet (the enforcement
# tests in tests/test_content_types.py).
_STRUCTURAL_SEPARATORS = frozenset(
    {chr(cp) for cp in _BARE_SEPARATORS} | set(_SPACED_SEPARATORS)
)


def safe_cell_text(value: str) -> str:
    """Neutralise structural delimiters inside an untrusted string before it
    is interpolated into a DELIMITED SINGLE-LINE render — a table cell, a
    ``" | "``-joined column, a ``"label: value"`` pair (GH-130, ported from
    ``origin/main``'s RT-002).

    Two composed steps: first collapse the full ``str.splitlines()`` break
    set plus the remaining C0/C1 controls to a space (confining the value to
    one line, full length — no truncation, unlike ``sanitize_text``'s 64-char
    log-line default); then neutralise the separator alphabet —
    ``_BARE_SEPARATORS`` everywhere, ``,``/``:``/``–``/``—``/``→`` everywhere
    except digit-flanked, and ``@`` only where it could form the spaced
    ``" @ "`` joiner (a real email address survives).

    Use :func:`safe_block_text` instead — never this — for a field whose
    declared contract is a MULTI-LINE MARKDOWN DOCUMENT, where a newline is
    the payload's own structure and ``|`` is table syntax."""
    text = safe_error_text(value, max_len=None).translate(_BARE_SEPARATORS)
    text = _SPACED_SEPARATOR_DIGIT_RE.sub(lambda m: _SPACED_SEPARATORS[m.group()], text)
    return _SPACED_SEPARATOR_AT_RE.sub(lambda m: _SPACED_SEPARATORS[m.group()], text)


_ID_NEUTRALISE = str.maketrans({
    "|": "/",
    "│": "/",
    "｜": "/",
    "<": "＜",
    ">": "＞",
    "(": "（",
    ")": "）",
    "[": "［",
    "]": "］",
})


def safe_id_text(value: str, *, max_len: int | None = 256) -> str:
    """Render an upstream identifier for a text fallback a model may copy back
    into a tool call (GH-156). Unlike :func:`safe_cell_text`, keeps
    ``= + / : , . _ - ! ~ @`` byte-exact (base64 padding, URNs); strips control
    characters, caps length, turns whitespace into ``_`` and neutralises only
    ``()[]<>|`` so an id cannot forge ``(id: ...)`` or ``, conversation: ...``."""
    text = safe_error_text(value, max_len=max_len)
    text = "_".join(text.split())
    return text.translate(_ID_NEUTRALISE)


def safe_block_text(value: str) -> str:
    """Strip control/escape characters from an untrusted string whose
    contract is a MULTI-LINE block (a markdown document), preserving
    ``\\n``/``\\t`` as content (SI-2, ported from ``origin/main``'s RT-001).

    ANSI/terminal escape introducers, NEL, U+2028/U+2029 and the rest of
    C0/DEL/C1 are neutralised; CR and CRLF normalise to ``\\n``. ``|`` is
    left alone — markdown table syntax here, not a column delimiter this
    renderer joined on."""
    return value.replace("\r\n", "\n").replace("\r", "\n").translate(
        _BLOCK_CONTROL_CHARS
    )


def redact(obj: Any, *, _depth: int = 0) -> Any:
    """Deep-copy with secret-named keys masked. Safe for log payloads."""
    if _depth > 8:
        return REDACTED
    if isinstance(obj, dict):
        return {
            k: REDACTED if isinstance(k, str) and _SECRET_KEY.search(k) else redact(v, _depth=_depth + 1)
            for k, v in obj.items()
        }
    if isinstance(obj, (list, tuple)):
        return [redact(v, _depth=_depth + 1) for v in obj]
    if isinstance(obj, str):
        return redact_value(obj)
    return obj
