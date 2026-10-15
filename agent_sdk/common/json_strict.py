"""Strict JSON parsing for request bodies on every protocol surface.

Python's ``json.loads`` yields a non-finite float in two ways, and neither
is JSON (RFC 8259 §6):

* the bare literals ``NaN``, ``Infinity`` and ``-Infinity``, and
* a number literal too large for a double, such as ``1e999`` or ``-1e400``,
  which ``float()`` silently turns into ``inf``/``-inf``.

Every outbound writer in the SDK uses ``allow_nan=False`` (GH-173), so a
client value that got in through a lenient parser would later crash the
writer mid-stream. ``loads_strict`` closes both gaps at ingress by hooking
``parse_constant`` AND ``parse_float``: every number token is checked, not
just the literal tokens. An integer literal past Python's digit limit
(``int_max_str_digits``) is mapped to the same error instead of a bare
``ValueError`` that some routes do not catch.

It also refuses any decoded string (key or value) that cannot be encoded as
UTF-8, i.e. a lone surrogate. JSON allows the escape ``"\\ud800"`` and
``json.loads`` decodes it as-is (and decodes raw ``ED A0 80`` bytes the same
way, via ``surrogatepass``), but every SDK writer refuses that character
(``dumps_strict``). Accepting it here let client input into stored task
state that no later read could serialize, so GET /v1/tasks failed for the
whole identity. Inbound and outbound now enforce the same rule.

All of these surface as ``json.JSONDecodeError`` with a fixed message, so
every route's existing parse-error branch handles them, and the error text
never echoes the offending token (SI-2).
"""

from __future__ import annotations

import json
import math
import re
from typing import Any, NoReturn

__all__ = ["dumps_strict", "loads_strict", "scrub_unencodable"]

# Every UTF-16 surrogate code point. A Python ``str`` holding one (alone, or
# as a pair of separate code points) cannot be encoded as UTF-8.
_SURROGATE_RE = re.compile("[\ud800-\udfff]")
_REPLACEMENT = "\ufffd"

_MESSAGE = "non-finite number not allowed"


def _reject(_token: str = "") -> NoReturn:
    raise json.JSONDecodeError(_MESSAGE, "", 0)


def _parse_float(token: str) -> float:
    value = float(token)
    if not math.isfinite(value):
        _reject()
    return value


def _parse_int(token: str) -> int:
    try:
        return int(token)
    except ValueError:
        # past sys.get_int_max_str_digits(); fixed text, never the digits
        raise json.JSONDecodeError("number too large", "", 0) from None


def loads_strict(raw: str | bytes | bytearray) -> Any:
    """``json.loads`` that raises ``json.JSONDecodeError`` for any input
    that would decode to a non-finite float (``NaN``, ``Infinity``,
    ``-Infinity``, or an overflowing literal like ``1e999``), to an
    integer past the interpreter's digit limit, or to a string (key or
    value) that is not UTF-8-encodable (a lone surrogate)."""
    value = json.loads(
        raw,
        parse_constant=_reject,
        parse_float=_parse_float,
        parse_int=_parse_int,
    )
    # Same rule the writers apply: re-encode with the C encoder and refuse
    # anything dumps_strict would refuse later. Every number is already
    # finite here, so the only failure left is a non-UTF-8 string.
    try:
        dumps_strict(value)
    except ValueError:
        raise json.JSONDecodeError("string not encodable as UTF-8", "", 0) from None
    return value


def dumps_strict(obj: Any) -> str:
    """``json.dumps`` that raises ``ValueError`` for any value no SDK writer
    can put on the wire. The one outbound counterpart of ``loads_strict``.

    Two cases raise:

    * a non-finite float (``allow_nan=False``), and
    * a string that cannot be encoded as UTF-8, such as a lone surrogate
      (``json.loads('"a\\ud800b"')``, common when an upstream API cuts an
      emoji in half). With ``ensure_ascii=False`` that character is copied
      into the output as-is, and every writer later calls ``.encode()`` on
      it, so the crash would land mid-stream, after every writability check.

    The returned string is therefore always safe to ``.encode("utf-8")``.
    The error text is fixed and never echoes the offending value (SI-2).
    ``UnicodeEncodeError`` is not re-raised as-is because its message
    carries the character itself."""
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("string not encodable as UTF-8") from None
    return text


def scrub_unencodable(obj: Any) -> Any:
    """Return ``obj`` with every surrogate code point in every ``str`` (dict
    keys included, at any depth of dict/list/tuple) replaced by U+FFFD.

    This is the store-side half of the rule ``dumps_strict`` enforces on the
    way out: text the SDK commits into a task (status messages, history,
    error text) passes through here first, so no stored value can later make
    a read fail. Returns the SAME object when nothing changed, so a caller can
    test ``scrub_unencodable(x) is x`` to skip a rebuild."""
    if isinstance(obj, str):
        return _SURROGATE_RE.sub(_REPLACEMENT, obj) if _SURROGATE_RE.search(obj) else obj
    if isinstance(obj, dict):
        changed = False
        out: dict[Any, Any] = {}
        for k, v in obj.items():
            nk, nv = scrub_unencodable(k), scrub_unencodable(v)
            changed = changed or nk is not k or nv is not v
            out[nk] = nv
        return out if changed else obj
    if isinstance(obj, (list, tuple)):
        items = [scrub_unencodable(v) for v in obj]
        if all(a is b for a, b in zip(items, obj)):
            return obj
        return type(obj)(items) if isinstance(obj, tuple) else items
    return obj
