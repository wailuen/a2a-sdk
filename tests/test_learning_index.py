"""CI assertion: workspace/learning/README.md index rows must equal LRN-*.md files on disk.

RT-003 fix: the redteam learning-check loop reads only the index table, so any
LRN file absent from the index is invisible to it.

RT-017 fix: frontmatter `id:` must match the filename LRN-NNN (LRN-058 invariant).
Supports both YAML-frontmatter format (`id: LRN-NNN` on its own line) and the
legacy heading format (`# LRN-NNN` as the first non-blank line).

RT-005 fix: every LRN Check clause that greps a repo path must reference a file
that actually exists — a dead path is a fail-open guard (LRN-079 pattern).
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


# Matches the path argument on a simple (non-piped) grep line inside a Check block:
#   grep -n "SYMBOL" agent_sdk/routes/mcp.py
#   grep -rn "PATTERN" agent_sdk/
# Rules:
#   - Only considers the portion before the first "|" (pipes produce separate commands)
#   - Captures the last whitespace-delimited token
#   - The token must contain "/" or end in a source extension (.py/.js/.ts/.md/.json/.yaml)
#     so bare shell flags (-u, -v, -20) and words like "test" are excluded
_SOURCE_EXT = re.compile(r"\.(py|js|ts|md|json|yaml|yml|toml|sh|txt|cfg|ini)$")
_GREP_LINE = re.compile(r"^\s*grep\b")

REPO_ROOT = Path(__file__).parent.parent


def _extract_check_grep_paths(path: Path) -> list[tuple[str, str]]:
    """Return (lrn_id, grep_path) pairs for every grep line inside a ## Check block."""
    text = path.read_text()
    m = LRN_FILE_PATTERN.match(path.name)
    lrn_id = m.group(1) if m else path.name

    results: list[tuple[str, str]] = []
    in_check = False
    in_fence = False
    for line in text.splitlines():
        stripped = line.strip()
        if re.match(r"^##\s+Check", stripped):
            in_check = True
            in_fence = False
            continue
        if in_check:
            if stripped.startswith("```"):
                in_fence = not in_fence
                if not in_fence:
                    in_check = False
                continue
            if in_fence and _GREP_LINE.match(line):
                # Only inspect the segment before any pipe
                segment = line.split("|")[0]
                tokens = segment.split()
                for token in reversed(tokens):
                    # Skip flags, shell redirects, and quoted pattern strings
                    if token.startswith(("-", "'", '"', "2>", ">")):
                        continue
                    # Must look like a repo path: only word chars, dots, slashes, hyphens
                    if not re.fullmatch(r"[\w./\-]+", token):
                        continue
                    if "/" in token or _SOURCE_EXT.search(token):
                        # Strip trailing slashes for directory paths
                        results.append((lrn_id, token.rstrip("/")))
                        break
    return results


def test_lrn_check_grep_paths_exist() -> None:
    """Every grep path in an LRN ## Check block must reference an existing repo path.

    A dead path (e.g. agent_sdk/mcp.py after a file move) is a fail-open guard
    that silently passes even when the guarded symbol is absent (LRN-079 / RT-005).
    """
    dead: list[str] = []
    for lrn_file in sorted(LEARNING_DIR.glob("LRN-*.md")):
        for lrn_id, grep_path in _extract_check_grep_paths(lrn_file):
            resolved = REPO_ROOT / grep_path
            if not resolved.exists():
                dead.append(f"{lrn_id}: grep path does not exist: {grep_path}")
    assert not dead, (
        "LRN Check clauses reference nonexistent paths (fail-open guards):\n"
        + "\n".join(dead)
    )
