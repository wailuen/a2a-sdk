"""CI assertion: workspace/learning/README.md index rows must equal LRN-*.md files on disk.

RT-003 fix: the redteam learning-check loop reads only the index table, so any
LRN file absent from the index is invisible to it.
"""

from __future__ import annotations

import re
from pathlib import Path


LEARNING_DIR = Path(__file__).parent.parent / "workspace" / "learning"
README = LEARNING_DIR / "README.md"
LRN_ID_PATTERN = re.compile(r"^\| (LRN-\d+) \|")
LRN_FILE_PATTERN = re.compile(r"(LRN-\d+)")


def _index_ids() -> list[str]:
    rows = []
    for line in README.read_text().splitlines():
        m = LRN_ID_PATTERN.match(line)
        if m:
            rows.append(m.group(1))
    return rows


def _disk_ids() -> list[str]:
    ids = []
    malformed = []
    for p in LEARNING_DIR.glob("LRN-*.md"):
        m = LRN_FILE_PATTERN.match(p.name)
        if m:
            ids.append(m.group(1))
        else:
            malformed.append(p.name)
    assert not malformed, (
        f"LRN-*.md file(s) without a parseable LRN-<digits> id: {sorted(malformed)}"
    )
    return sorted(ids)


def test_learning_index_row_count_matches_disk_files() -> None:
    index_ids = _index_ids()
    disk_ids = _disk_ids()

    missing_from_index = sorted(set(disk_ids) - set(index_ids))
    orphaned_in_index = sorted(set(index_ids) - set(disk_ids))

    assert not missing_from_index, (
        f"LRN files on disk with no index row (invisible to redteam loop): {missing_from_index}"
    )
    assert not orphaned_in_index, (
        f"Index rows with no matching file on disk: {orphaned_in_index}"
    )
    assert len(index_ids) == len(disk_ids), (
        f"Row count {len(index_ids)} != file count {len(disk_ids)}"
    )


def test_learning_index_ids_are_unique() -> None:
    index_ids = _index_ids()
    seen: dict[str, int] = {}
    for lrn_id in index_ids:
        seen[lrn_id] = seen.get(lrn_id, 0) + 1
    duplicates = {k: v for k, v in seen.items() if v > 1}
    assert not duplicates, f"Duplicate IDs in README index: {duplicates}"
