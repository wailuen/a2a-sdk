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
#   grep -n "SYMBOL" agent_sdk/clients/*.py
# Rules:
#   - Splits on the first UNQUOTED "|" only — a pipe inside the quoted grep pattern
#     (e.g. grep -n 'a\|b' foo.py) is not a shell metacharacter and must not truncate
#     the line before the path argument that follows it
#   - Captures every whitespace-delimited path-shaped token of that segment,
#     not only the trailing one — a multi-file grep names several paths (RT-003)
#   - A token must contain "/" or end in a source extension (.py/.js/.ts/.md/.json/.yaml)
#     so bare shell flags (-u, -v, -20) and words like "test" are excluded
#   - A token may contain glob characters ("*", "?") — a glob path must still be
#     seen by the dead-path guard (RT-009), not silently dropped by the filter
#   - A grep's file arguments may spill onto backslash-continued physical
#     lines; those continuation lines never start with "grep" themselves, so
#     they are joined into one logical line before extraction (RT-003) —
#     otherwise every path on a continuation line is invisible to the guard
#   - Every fenced block under a "## Check" heading is scanned, not just the first —
#     scanning stops only at the next "##" heading, since a Check section may contain
#     more than one fenced command
#   - A grep command written as inline code (single backticks) in prose under
#     "## Check" is scanned too, not only fenced (triple-backtick) blocks (RT-009)
_SOURCE_EXT = re.compile(r"\.(py|js|ts|md|json|yaml|yml|toml|sh|txt|cfg|ini)$")
_GREP_LINE = re.compile(r"^\s*grep\b")
_CHECK_HEADING = re.compile(r"^##\s+Check\b")
_ANY_HEADING = re.compile(r"^##\s+")
_INLINE_CODE = re.compile(r"`([^`]+)`")
_PATH_TOKEN = re.compile(r"[\w./\-*?]+")

REPO_ROOT = Path(__file__).parent.parent


def _segment_before_unquoted_pipe(line: str) -> str:
    """Return the prefix of `line` up to (not including) the first "|" that is
    outside single/double quotes. Returns the full line if no such "|" exists."""
    quote: str | None = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch == "|":
            return line[:i]
    return line


def _grep_paths_from_line(line: str) -> list[str]:
    """Return every repo-path token of a single (already logical, i.e.
    backslash-continuation already joined) grep command, in left-to-right
    order. A multi-file grep names more than one path — the trailing token
    alone is not enough (RT-003)."""
    if not _GREP_LINE.match(line):
        return []
    segment = _segment_before_unquoted_pipe(line)
    paths: list[str] = []
    for token in segment.split():
        # Skip flags, shell redirects, and quoted pattern strings
        if token.startswith(("-", "'", '"', "2>", ">")):
            continue
        # Must look like a repo path: word chars, dots, slashes, hyphens, globs
        if not _PATH_TOKEN.fullmatch(token):
            continue
        if "/" in token or _SOURCE_EXT.search(token):
            # Strip trailing slashes for directory paths
            paths.append(token.rstrip("/"))
    return paths


def _extract_check_grep_paths(path: Path) -> list[tuple[str, str]]:
    """Return (lrn_id, grep_path) pairs for every grep command inside a
    ## Check block — both fenced (```) blocks and inline (`) code spans.

    A grep command's file arguments may spill onto backslash-continued
    physical lines (`grep ... \\` / `  path.py \\` / `  path2.py`); those
    continuation lines never start with `grep`, so they are joined into one
    logical line before path extraction (RT-003)."""
    text = path.read_text()
    m = LRN_FILE_PATTERN.match(path.name)
    lrn_id = m.group(1) if m else path.name

    results: list[tuple[str, str]] = []
    in_check = False
    in_fence = False
    pending: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if in_fence:
            if stripped.startswith("```"):
                in_fence = False
                pending = []
                continue
            if in_check:
                fragment = line.rstrip()
                if fragment.endswith("\\"):
                    pending.append(fragment[:-1])
                    continue
                pending.append(fragment)
                logical_line = " ".join(p.strip() for p in pending)
                pending = []
                for grep_path in _grep_paths_from_line(logical_line):
                    results.append((lrn_id, grep_path))
            continue
        if stripped.startswith("```"):
            in_fence = True
            continue
        if _ANY_HEADING.match(stripped):
            in_check = bool(_CHECK_HEADING.match(stripped))
            continue
        if in_check:
            for span in _INLINE_CODE.findall(line):
                for grep_path in _grep_paths_from_line(span):
                    results.append((lrn_id, grep_path))
    return results


def _grep_path_is_dead(grep_path: str) -> bool:
    """True if `grep_path` cannot resolve against REPO_ROOT.

    Handles shell globs (`agent_sdk/model_clients/*.py`): a glob with no
    matching files still makes grep exit non-zero with no output, so a Check
    clause pointed at a glob over a nonexistent directory passes vacuously
    just like a dead plain path (RT-007 / LRN-079).
    """
    if "*" not in grep_path:
        return not (REPO_ROOT / grep_path).exists()
    dir_parts: list[str] = []
    for part in grep_path.split("/"):
        if "*" in part:
            break
        dir_parts.append(part)
    base_dir = REPO_ROOT.joinpath(*dir_parts) if dir_parts else REPO_ROOT
    return not base_dir.is_dir()


def _check_path_exists(grep_path: str) -> bool:
    """A Check grep path is alive if the literal path exists, or — for a glob
    token — if it resolves to at least one file/dir (RT-009: a literal
    Path.exists() on a "*.py" component is always False and would flag every
    legitimate glob path as dead)."""
    if "*" in grep_path or "?" in grep_path:
        return len(list(REPO_ROOT.glob(grep_path))) > 0
    return (REPO_ROOT / grep_path).exists()


def test_segment_before_unquoted_pipe_ignores_pipe_inside_quotes() -> None:
    line = "grep -n '!rt || rt.findingsCount === 0' agent_sdk/routes/mcp.py"
    assert _segment_before_unquoted_pipe(line) == line


def test_segment_before_unquoted_pipe_splits_on_real_shell_pipe() -> None:
    line = r'grep -n "unitGate\|phaseGate\|testsRed" agent_sdk/routes/mcp.py | grep -v "null"'
    assert _segment_before_unquoted_pipe(line) == (
        r'grep -n "unitGate\|phaseGate\|testsRed" agent_sdk/routes/mcp.py '
    )


def test_extract_check_grep_paths_finds_path_after_quoted_pipe(tmp_path: Path) -> None:
    content = (
        "---\nid: LRN-999\n---\n\n"
        "## Check\n```\n"
        "grep -n '!rt || rt.findingsCount === 0' agent_sdk/routes/mcp.py\n"
        "```\n"
    )
    lrn_file = tmp_path / "LRN-999-fixture.md"
    lrn_file.write_text(content)
    assert _extract_check_grep_paths(lrn_file) == [
        ("LRN-999", "agent_sdk/routes/mcp.py")
    ]


def test_extract_check_grep_paths_scans_every_fenced_block_in_section(
    tmp_path: Path,
) -> None:
    content = (
        "---\nid: LRN-998\n---\n\n"
        "## Check\n"
        "Run this first:\n```\n"
        "echo hello\n"
        "```\n"
        "Then verify:\n```\n"
        "grep -n 'ADR-001' agent_sdk/routes/mcp.py\n"
        "```\n"
    )
    lrn_file = tmp_path / "LRN-998-fixture.md"
    lrn_file.write_text(content)
    assert _extract_check_grep_paths(lrn_file) == [
        ("LRN-998", "agent_sdk/routes/mcp.py")
    ]


def test_extract_check_grep_paths_stops_at_next_heading(tmp_path: Path) -> None:
    content = (
        "---\nid: LRN-997\n---\n\n"
        "## Check\n```\n"
        "echo nothing to see\n"
        "```\n"
        "## Prevention\n```\n"
        "grep -n 'ADR-001' agent_sdk/routes/mcp.py\n"
        "```\n"
    )
    lrn_file = tmp_path / "LRN-997-fixture.md"
    lrn_file.write_text(content)
    assert _extract_check_grep_paths(lrn_file) == []


def test_extract_check_grep_paths_captures_glob_token(tmp_path: Path) -> None:
    """RT-009: a `*.py` glob token must not be dropped by the token filter —
    dropping it silently turns the guard fail-open (LRN-104 pattern)."""
    content = (
        "---\nid: LRN-996\n---\n\n"
        "## Check\n```\n"
        'grep -n "import " agent_sdk/clients/*.py | grep -v "^Binary"\n'
        "```\n"
    )
    lrn_file = tmp_path / "LRN-996-fixture.md"
    lrn_file.write_text(content)
    assert _extract_check_grep_paths(lrn_file) == [
        ("LRN-996", "agent_sdk/clients/*.py")
    ]


def test_extract_check_grep_paths_captures_inline_backtick_grep(
    tmp_path: Path,
) -> None:
    """RT-009: a grep command inside single backticks (prose, not a fenced
    block) must still be scanned under ## Check — LRN-105's actual shape."""
    content = (
        "---\nid: LRN-995\n---\n\n"
        "## Check\n\n"
        '`grep -n "except Exception" agent_sdk/model_clients/*.py` — for every '
        "hit, verify no more-specific category applies.\n"
    )
    lrn_file = tmp_path / "LRN-995-fixture.md"
    lrn_file.write_text(content)
    assert _extract_check_grep_paths(lrn_file) == [
        ("LRN-995", "agent_sdk/model_clients/*.py")
    ]


def test_extract_check_grep_paths_inline_backtick_outside_check_ignored(
    tmp_path: Path,
) -> None:
    content = (
        "---\nid: LRN-993\n---\n\n"
        "## What went wrong\n\n"
        '`grep -n "x" agent_sdk/nonexistent/*.py` should not be picked up here.\n'
    )
    lrn_file = tmp_path / "LRN-993-fixture.md"
    lrn_file.write_text(content)
    assert _extract_check_grep_paths(lrn_file) == []


def test_path_exists_glob_dead_when_no_matches() -> None:
    assert not _check_path_exists("agent_sdk/clients/*.py")
    assert not _check_path_exists("agent_sdk/model_clients/*.py")


def test_path_exists_glob_alive_when_matches() -> None:
    assert _check_path_exists("agent_sdk/agent/*.py")


def test_check_grep_dead_glob_path_is_detected(tmp_path: Path) -> None:
    """End-to-end regression for RT-009: a Check block whose grep path is a
    dead glob must be flagged, not silently skipped."""
    content = (
        "---\nid: LRN-992\n---\n\n"
        "## Check\n```\n"
        'grep -n "x" agent_sdk/nonexistent_dir/*.py\n'
        "```\n"
    )
    lrn_file = tmp_path / "LRN-992-fixture.md"
    lrn_file.write_text(content)
    pairs = _extract_check_grep_paths(lrn_file)
    assert pairs == [("LRN-992", "agent_sdk/nonexistent_dir/*.py")]
    _, grep_path = pairs[0]
    assert not _check_path_exists(grep_path)


def test_extract_check_grep_paths_joins_backslash_continued_lines(
    tmp_path: Path,
) -> None:
    """RT-003: a Check grep whose file arguments spill onto backslash-continued
    lines must have every path extracted — a physical continuation line never
    starts with `grep`, so a guard anchored per physical line on
    `^\\s*grep\\b` is blind to it (LRN-028/036/037 pattern), and a multi-file
    grep names more than one path, so every one must be captured, not only
    the trailing token."""
    content = (
        "---\nid: LRN-991\n---\n\n"
        "## Check\n```\n"
        'grep -n "prevSigs = new Set" \\\n'
        "  harness/workflows/wave-cycle.js \\\n"
        "  template/.claude/workflows/wave-cycle.js\n"
        "```\n"
    )
    lrn_file = tmp_path / "LRN-991-fixture.md"
    lrn_file.write_text(content)
    assert _extract_check_grep_paths(lrn_file) == [
        ("LRN-991", "harness/workflows/wave-cycle.js"),
        ("LRN-991", "template/.claude/workflows/wave-cycle.js"),
    ]


def test_check_grep_dead_path_on_continuation_line_is_detected(
    tmp_path: Path,
) -> None:
    """End-to-end regression for RT-003: the second path of a backslash-
    continued multi-file grep must be reachable by the dead-path guard, not
    silently invisible to it.

    Uses a path that is dead regardless of whether the optional template/
    peer-repo checkout (LRN-071) is present in this working tree — unlike a
    real template/ file path, which would stop being "dead" bait the moment
    someone actually clones template/ locally (see test_workflow_sync.py's
    xfail(strict) guards for that scenario)."""
    content = (
        "---\nid: LRN-990\n---\n\n"
        "## Check\n```\n"
        'grep -n "prevSigs = new Set" \\\n'
        "  harness/workflows/wave-cycle.js \\\n"
        "  template/.claude/workflows/does-not-exist.js\n"
        "```\n"
    )
    lrn_file = tmp_path / "LRN-990-fixture.md"
    lrn_file.write_text(content)
    pairs = _extract_check_grep_paths(lrn_file)
    dead = [grep_path for _, grep_path in pairs if not _check_path_exists(grep_path)]
    assert dead == ["template/.claude/workflows/does-not-exist.js"]


def test_lrn_check_grep_paths_exist() -> None:
    """Every grep path in an LRN ## Check block must reference an existing repo path.

    A dead path (e.g. agent_sdk/mcp.py after a file move) is a fail-open guard
    that silently passes even when the guarded symbol is absent (LRN-079 / RT-005).
    """
    dead: list[str] = []
    for lrn_file in sorted(LEARNING_DIR.glob("LRN-*.md")):
        for lrn_id, grep_path in _extract_check_grep_paths(lrn_file):
            if not _check_path_exists(grep_path):
                dead.append(f"{lrn_id}: grep path does not exist: {grep_path}")
    assert not dead, (
        "LRN Check clauses reference nonexistent paths (fail-open guards):\n"
        + "\n".join(dead)
    )


def test_grep_path_is_dead_detects_glob_over_missing_directory() -> None:
    """RT-007: a glob token (`dir/*.py`) must be checked like any other path.

    Before this fix, `_extract_check_grep_paths`'s fullmatch regex rejected
    any token containing `*`, so a Check clause glob over a moved/renamed
    directory (agent_sdk/model_clients/*.py, which does not exist) was
    silently skipped rather than flagged dead — the guard itself was fail-open.
    """
    assert _grep_path_is_dead("agent_sdk/model_clients/*.py")
    assert not _grep_path_is_dead("agent_sdk/agent/*.py")


def test_extract_check_grep_paths_captures_glob_tokens(tmp_path: Path) -> None:
    lrn_file = tmp_path / "LRN-999-example.md"
    lrn_file.write_text(
        "---\nid: LRN-999\n---\n\n## Check\n\n"
        '```bash\ngrep -n "except Exception" agent_sdk/model_clients/*.py\n```\n'
    )
    results = _extract_check_grep_paths(lrn_file)
    assert results == [("LRN-999", "agent_sdk/model_clients/*.py")]
