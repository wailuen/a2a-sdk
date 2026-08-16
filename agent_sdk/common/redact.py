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

# C-007: every char str.splitlines() treats as a line break (\n \r \v \f
# \x1c \x1d \x1e \x85 U+2028 U+2029) falls inside these three spans, along
# with the rest of C0, DEL and C1 — closing both the SI-2 log/terminal-
# injection surface this helper originally guarded and the GH-130/RT-004
# to_plain_text() row-fabrication surface a CR/LF-only filter left open.
_CONTROL_CHARS = dict.fromkeys(
    [*range(0x20), 0x7F, *range(0x80, 0xA0), 0x2028, 0x2029], " "
)

# RT-001: the block variant of the same span set, for payloads whose contract
# is MULTI-LINE text (markdown documents) rather than a single-line delimited
# cell. ``\n`` and ``\t`` are legitimate CONTENT there, not structure, so they
# survive; every other C0/DEL/C1 char — crucially ESC (0x1B) and CSI (0x9B),
# the terminal-injection introducers, plus NEL (0x85) and U+2028/U+2029 —
# still collapses to a space. ``\r`` is excluded from this map and normalised
# to ``\n`` before translation (a bare CR rewrites the current terminal line,
# the classic log-injection trick, and CRLF must not become a double break).
_BLOCK_CONTROL_CHARS = {
    cp: " "
    for cp in [*range(0x20), 0x7F, *range(0x80, 0xA0), 0x2028, 0x2029]
    if cp not in (0x09, 0x0A, 0x0D)
}


def redact_value(text: str) -> str:
    return _BEARER_VALUE.sub(r"\1 " + REDACTED, text)


def safe_error_text(value: str, *, max_len: int | None = 64) -> str:
    """Strip Unicode control/line-break characters and cap length before an
    untrusted (model-/caller-supplied) string reaches a log line, error
    message, or wire payload (SI-2). Pass ``max_len=None`` to preserve the
    untrusted value's full length for callers where truncation is not part
    of the contract (e.g. table-cell sanitisation)."""
    text = value if max_len is None else value[:max_len]
    return text.translate(_CONTROL_CHARS).strip()


# GH-130 — SEPARATOR ALPHABET (RT-002: promoted here from models/content_types.py,
# where it was module-private). Every character below is one that some delimited
# ``to_plain_text()``/``to_markdown()`` renderer inserts BETWEEN or AROUND
# interpolated field values: " | " columns, ": " label/value pairs, "k=v" and ", "
# category joins, the "<email>" / "(type)" / "[unread]" pairs, and the " – " /
# " — " / " @ " / " → " joiners. An untrusted value that smuggles one of these in
# fabricates a boundary, so one field renders as two — the reader (human or model)
# sees a record that does not exist.
#
# This map is applied UNCONDITIONALLY by safe_cell_text(). It deliberately replaced
# an earlier design in which each renderer opted into the subset of delimiters it
# happened to use; four successive review rounds each found one more
# renderer/delimiter pair left uncovered. Applying the union to every cell makes a
# NEW renderer safe by default rather than safe-if-its-author-remembers.
#
# Only SEPARATORS belong here. Value glyphs a renderer emits from its own trusted
# numeric/enum fields — "-", "+", "%", ".", "/", "▲"/"▼" — are NOT separators: a
# value cannot be split in two with them, and neutralising "-" in particular would
# mangle every ISO date. Line-anchored markers ("  - " bullets, the "---" rule) need
# no entry either: safe_error_text() already collapses the whole str.splitlines()
# break set, so an untrusted value is confined to one line and can never reach a
# line-start position.
#
# No replacement is itself a separator, so a neutralised character can never collide
# with the literal the f-string inserts.
# Separators inserted in BARE form, with no surrounding space: "k=v",
# "name<email>", "(type)", "[unread]", and the " | " column join (bare-neutralised
# too — it has no legitimate compact use in a cell, and the GH-130 column case is the
# one this all started with). A value carrying any of these anywhere can fabricate a
# boundary, so they are always replaced.
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

# Separators only ever inserted in SPACED form — ": ", ", ", " @ ", " – ", " — ",
# " → ". Two different legitimate-compact-use cases hide behind that one list, so
# they get two different rules (RT-010). The original single rule — neutralise
# only when whitespace sits on either side, or the occurrence sits at the value's
# own boundary — left a real gap: "a,b" has no adjacent whitespace on either side,
# so its comma survived untouched, and a category-key value shaped like "a,b"
# rendered as two categories where the true count was one (demonstrated end to
# end by tests/test_content_types.py::
# test_multi_category_chart_compact_category_key_comma_does_not_fabricate_pair).
#
# ",", ":", "–", "—", "→" — their only legitimate compact use is a NUMERIC
# literal, range, or timestamp: "1,234" (thousands), "09:30" (time-of-day),
# "20–30"/"9–5" (a range), "5→10" (a delta). An occurrence flanked by an ASCII
# digit on BOTH sides is left alone; every other compact occurrence — flanked by
# a letter, punctuation, or a string boundary — is exactly the GH-130
# fabrication shape and is now neutralised regardless of adjacent whitespace.
_DIGIT_FLANK_EXEMPT = frozenset({",", ":", "–", "—", "→"})
_SPACED_SEPARATOR_DIGIT_RE = re.compile(
    r"(?<!\d)[{c}]|[{c}](?!\d)".format(c="".join(_DIGIT_FLANK_EXEMPT))
)

# "@" is the sole remaining exception, and a deliberately ACCEPTED residual
# (RT-010) — do not extend the digit-flank rule to it. Its overwhelmingly common
# compact use is a real email address, flanked by LETTERS rather than digits, so
# a digit-flank rule would rewrite "alice@corp.com" to "alice＠corp.com" in every
# render — the SDK's own renderers depend on the un-mangled form surviving
# (UserProfile/UserList/EmailList/CalendarEvents all interpolate a raw `email`
# field next to this exact character, pinned by dedicated tests in
# tests/test_content_types.py). safe_cell_text operates on one value at a time
# with no field-level type information, so it cannot tell a genuine compact
# email apart from a hostile compact "@" smuggled into some other field (e.g. a
# location name) — that narrower gap is knowingly left open, scoped to this one
# character, on the original whitespace-adjacency rule the whole alphabet used
# to share. Closing it fully would need per-field type information this
# value-level helper deliberately does not have.
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
    """Neutralise structural delimiters inside an untrusted string before it is
    interpolated into a DELIMITED SINGLE-LINE render — a table cell, a
    ``" | "``-joined column, a ``"label: value"`` pair (GH-130).

    THE PUBLIC HELPER FOR THE DELIMITER-SAFETY CONTRACT (RT-002). Every
    ``ContentModel.to_plain_text()`` implementation — the SDK's own and third-party
    domain cards alike (DESIGN §4.0/§4.3) — must route untrusted field values through
    this function. It was previously ``models.content_types._sanitize_cell``, private
    and unexported, while the contract it implements was declared mandatory for
    third-party code in three places; the only way to comply was to hand-rebuild the
    separator alphabet per card module, which is precisely the divergent
    reimplementation the C-007 redaction family exists to prevent (and which four
    consecutive review rounds proved nobody gets right by hand).

    Two composed steps, neither sufficient alone:

    1. :func:`safe_error_text` with ``max_len=None`` collapses the full
       ``str.splitlines()`` break set — CR, LF, VT, FF, FS/GS/RS, NEL, LINE/PARAGRAPH
       SEPARATOR — plus the remaining C0/C1 controls to a space, confining the value
       to one line. ``max_len=None`` because a cell must keep its full untrusted
       length, unlike the 64-char log-line contract ``safe_error_text`` defaults to.
    2. The separator alphabet is neutralised on top — the step a delimited render
       needs and a generic log/error sanitiser does not: ``_BARE_SEPARATORS``
       everywhere; ``,``/``:``/``–``/``—``/``→`` everywhere EXCEPT where flanked by a
       digit on both sides (so ``"1,234"``/``"09:30"`` survive, but a compact
       occurrence between letters — the RT-010 gap — does not); and ``@`` only where
       an occurrence could form the spaced ``" @ "`` joiner (so a real email address
       survives — the one character-level exception this function still accepts,
       see ``_SPACED_SEPARATOR_AT_RE``'s module comment).

    There is no per-renderer opt-in: the full alphabet is applied to every cell, so a
    renderer is delimiter-safe by construction.

    Use :func:`safe_block_text` instead — never this — for a field whose declared
    contract is a MULTI-LINE MARKDOWN DOCUMENT (``MarketBriefing.prose``,
    ``TextSection.content``), where a newline is the payload's own structure and
    ``|`` is table syntax. Choose the helper by the FIELD's contract, never by the
    enclosing method's name.
    """
    text = safe_error_text(value, max_len=None).translate(_BARE_SEPARATORS)
    text = _SPACED_SEPARATOR_DIGIT_RE.sub(lambda m: _SPACED_SEPARATORS[m.group()], text)
    return _SPACED_SEPARATOR_AT_RE.sub(lambda m: _SPACED_SEPARATORS[m.group()], text)


def safe_block_text(value: str) -> str:
    """Strip control/escape characters from an untrusted string whose contract
    is a MULTI-LINE block (a markdown document), preserving ``\\n``/``\\t`` as
    content (SI-2, RT-001).

    The counterpart to :func:`safe_error_text`, which collapses *every* line
    break because its callers interpolate into a single-line, delimiter-joined
    render where a break fabricates a row. That threat does not exist here:
    ``MarketBriefing`` is the SDK's sole prose-exception type (DESIGN §4.3) —
    its ``to_markdown()`` output *is* the A2A/AG-UI DataPart value and the MCP
    ``structuredContent {"markdown": ...}`` payload, so a newline is the
    payload's own structure, not an injected delimiter, and nothing downstream
    re-parses it positionally. ``|`` is likewise left alone: it is markdown
    table syntax here, not a column delimiter this renderer joined on.

    What remains genuinely dangerous — ANSI/terminal escape introducers, NEL,
    U+2028/U+2029 and the rest of C0/DEL/C1 — is still neutralised, so the SI-2
    log/terminal-injection guard holds. CR and CRLF normalise to ``\\n``.
    """
    return value.replace("\r\n", "\n").replace("\r", "\n").translate(
        _BLOCK_CONTROL_CHARS
    )


def frame_locations(exc: BaseException, *, limit: int = 5) -> str:
    """Format the last ``limit`` traceback frame locations as ``file:line``
    for a diagnostic log line (SI-2). Only ``FrameSummary.filename``/
    ``.lineno`` are used — never ``.line``, which echoes source text that
    could itself embed a caller-derived literal.

    THE INVARIANT, not a census: every generic ``except Exception`` catch-all
    that swallows a dispatch or upstream-call failure logs the exception TYPE
    plus this helper, so no failure becomes undiagnosable (LRN-044). Callers
    are found with ``grep -rn frame_locations agent_sdk/`` — deliberately not
    enumerated here, because a hand-maintained list of "N call sites across M
    files" goes stale the moment a surface is added (it already had, twice)
    and a stale census reads as permission to skip the contract. The current
    surfaces are routes/mcp.py, routes/admin.py, agent/loop.py's dispatch
    catch-alls, contrib/commitments/executor.py's ``_fire``, and both model
    clients (agent/bedrock.py, agent/openai_client.py); parity between those
    last two is pinned by
    tests/test_redact.py::test_both_model_clients_log_frame_locations."""
    return "|".join(
        f"{frame.filename}:{frame.lineno}"
        for frame in traceback.extract_tb(exc.__traceback__)[-limit:]
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
