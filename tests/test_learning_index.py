"""CI assertion: workspace/learning/README.md index rows must equal LRN-*.md files on disk.

RT-003 fix: the redteam learning-check loop reads only the index table, so any
LRN file absent from the index is invisible to it.

RT-017 fix: frontmatter `id:` must match the filename LRN-NNN (LRN-058 invariant).
Supports both YAML-frontmatter format (`id: LRN-NNN` on its own line) and the
legacy heading format (`# LRN-NNN` as the first non-blank line).
"""

from __future__ import annotations

import re
from pathlib import Path


LEARNING_DIR = Path(__file__).parent.parent / "workspace" / "learning"
README = LEARNING_DIR / "README.md"
LRN_ID_PATTERN = re.compile(r"^\| (LRN-\d+) \|")
LRN_FILE_PATTERN = re.compile(r"(LRN-\d+)")
# Matches YAML frontmatter id line: `id: LRN-NNN`
FRONTMATTER_ID_PATTERN = re.compile(r"^id:\s*(LRN-\d+)")
# Matches legacy heading: `# LRN-NNN` (optionally followed by —/- and title)
HEADING_ID_PATTERN = re.compile(r"^#\s+(LRN-\d+)")


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


def _extract_declared_id(path: Path) -> str | None:
    """Return the LRN id declared inside the file (YAML frontmatter or heading)."""
    text = path.read_text()
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = FRONTMATTER_ID_PATTERN.match(line)
        if m:
            return m.group(1)
        m = HEADING_ID_PATTERN.match(line)
        if m:
            return m.group(1)
        # Stop scanning after the first non-blank, non-separator line that
        # didn't match — avoids picking up id: mentions inside body text.
        # Exception: skip YAML front-matter delimiter lines (---).
        if line != "---":
            break
    return None


def test_learning_frontmatter_id_matches_filename() -> None:
    """Every LRN file's declared id (YAML or heading) must match its filename.

    Prevents the LRN-058 / LRN-085 copy-paste defect where a codify agent
    duplicates a prior file's frontmatter and updates title but forgets id.
    """
    mismatches: list[str] = []
    no_id: list[str] = []
    for path in sorted(LEARNING_DIR.glob("LRN-*.md")):
        m = LRN_FILE_PATTERN.match(path.name)
        if not m:
            continue
        filename_id = m.group(1)
        declared_id = _extract_declared_id(path)
        if declared_id is None:
            no_id.append(path.name)
        elif declared_id != filename_id:
            mismatches.append(
                f"{path.name}: filename={filename_id}, declared={declared_id}"
            )
    assert not no_id, (
        f"LRN files with no parseable id (add YAML 'id:' or '# LRN-NNN' heading): "
        f"{no_id}"
    )
    assert not mismatches, (
        f"LRN files whose declared id does not match their filename: {mismatches}"
    )
