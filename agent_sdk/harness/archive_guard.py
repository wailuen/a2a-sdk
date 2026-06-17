"""GH-40: archive guard helpers for wave-cycle archive phase.

These pure functions are used by the pre-archive commit-check gate in
wave-cycle.js (via agent call) to determine whether any Creates: files are
still uncommitted (dirty) at archive time.

Both functions are free of I/O so they are trivially unit-testable.
"""

from __future__ import annotations


def parse_git_status(output: str) -> set[str]:
    """Parse ``git status --short`` output into a set of dirty file paths.

    ``git status --short`` emits lines of the form::

        XY path/to/file

    where ``XY`` is a two-character status code and the path starts at
    column 3 (after a space separator).  Untracked files use ``??``.

    Args:
        output: Raw stdout from ``git status --short``.

    Returns:
        Set of file paths (stripped, no leading status chars).
    """
    paths: set[str] = set()
    for line in output.splitlines():
        if not line.strip():
            continue
        # Status column is exactly 2 chars; separator is a space; path follows.
        if len(line) < 4:
            continue
        path_part = line[3:].strip()
        if not path_part:
            continue
        # Rename (R) and copy (C) entries have the form "old-path -> new-path".
        # The new path is what matters for archive checking — the old path was
        # already committed under its original name.
        if ' -> ' in path_part:
            _, new_path = path_part.split(' -> ', 1)
            path_part = new_path.strip()
        if path_part:
            paths.add(path_part)
    return paths


def uncommitted_creates(dirty: set[str], all_creates: list[str]) -> list[str]:
    """Return dirty paths that overlap with wave Creates: entries.

    A dirty path *overlaps* a Creates: entry when either:

    - The dirty path exactly equals the Creates: entry.
    - The Creates: entry is a prefix of the dirty path (directory Creates:).
    - The dirty path is a prefix of the Creates: entry (file inside a
      Creates: subtree that was not yet created but a parent dir was touched).

    The function is conservative: any ambiguous prefix relationship is
    treated as an overlap and included in the result.

    Args:
        dirty: Set of paths from :func:`parse_git_status`.
        all_creates: List of Creates: paths from ``wave.allCreates``.

    Returns:
        List of dirty paths that match a Creates: entry (offenders).
        Empty list means all Creates: files are committed — safe to archive.
    """
    offenders: list[str] = []
    for dirty_path in dirty:
        for creates_path in all_creates:
            # Normalise: strip trailing slashes for prefix comparison
            dp = dirty_path.rstrip("/")
            cp = creates_path.rstrip("/")
            if dp == cp:
                offenders.append(dirty_path)
                break
            # dirty is inside a Creates: directory
            if dirty_path.startswith(creates_path.rstrip("/") + "/"):
                offenders.append(dirty_path)
                break
            # Creates: path is inside a dirty directory (parent was touched)
            if creates_path.startswith(dirty_path.rstrip("/") + "/"):
                offenders.append(dirty_path)
                break
    return offenders
