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

All of these surface as ``json.JSONDecodeError`` with one fixed message, so
every route's existing parse-error branch handles them, and the error text
never echoes the offending token (SI-2).
"""

from __future__ import annotations

import json
import math
from typing import Any, NoReturn

__all__ = ["loads_strict"]

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
    ``-Infinity``, or an overflowing literal like ``1e999``) or to an
    integer past the interpreter's digit limit."""
    return json.loads(
        raw,
        parse_constant=_reject,
        parse_float=_parse_float,
        parse_int=_parse_int,
    )
