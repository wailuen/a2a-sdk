"""Shared text helpers."""

from __future__ import annotations

from collections.abc import Sequence


def cap_whole_entries(
    entries: Sequence[str],
    limit: int,
    *,
    sep: str = "; ",
    max_entries: int | None = None,
    omitted: int = 0,
) -> tuple[str, int]:
    """Join whole entries within ``limit`` chars; return (text, entries kept) (C-075).

    An entry that does not fit is skipped and later shorter ones are still
    tried. When any entry is left out (``omitted`` counts those the caller
    already dropped), the text ends ``<sep>…and N more``; its length is
    reserved in every fit check, so the result never exceeds ``limit``.
    """
    if omitted == 0 and (max_entries is None or max_entries >= len(entries)):
        full = sep.join(entries)
        if len(full) <= limit:
            return full, len(entries)
    kept: list[str] = []
    used = 0
    for entry in entries:
        if max_entries is not None and len(kept) >= max_entries:
            break
        left = omitted + len(entries) - len(kept) - 1
        tail_len = len(sep) + len(f"…and {left} more")
        added = len(entry) + (len(sep) if kept else 0)
        if used + added + tail_len > limit:
            continue
        kept.append(entry)
        used += added
    left_out = omitted + len(entries) - len(kept)
    more = f"…and {left_out} more"
    return sep.join([*kept, more]), len(kept)
