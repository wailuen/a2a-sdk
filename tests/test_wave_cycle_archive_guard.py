"""GH-40: wave-cycle archive guard — uncommitted Creates: files block archive.

Tests the parse_git_status helper that the archive gate uses to cross-reference
`git status --short` output against wave.allCreates paths.

Test-first: this file was written BEFORE archive_guard.py existed (RED),
then the implementation was written to make it GREEN.
"""

from __future__ import annotations

import pytest

from agent_sdk.harness.archive_guard import (
    parse_git_status,
    uncommitted_creates,
)


# ---------------------------------------------------------------------------
# parse_git_status — parse `git status --short` into a set of paths
# ---------------------------------------------------------------------------


def test_parse_empty_output():
    """Clean working tree → empty set."""
    assert parse_git_status("") == set()


def test_parse_untracked_file():
    """?? prefix → untracked file included."""
    result = parse_git_status("?? src/tools/new_tool.py\n")
    assert "src/tools/new_tool.py" in result


def test_parse_modified_unstaged():
    """ M prefix → modified but not staged."""
    result = parse_git_status(" M src/routes/a2a.py\n")
    assert "src/routes/a2a.py" in result


def test_parse_modified_staged():
    """M  prefix → modified and staged."""
    result = parse_git_status("M  src/routes/a2a.py\n")
    assert "src/routes/a2a.py" in result


def test_parse_added_staged():
    """A  prefix → new file staged."""
    result = parse_git_status("A  tests/test_new.py\n")
    assert "tests/test_new.py" in result


def test_parse_deleted():
    """D  or  D prefix → deleted file included."""
    result = parse_git_status(" D old_file.py\n")
    assert "old_file.py" in result


def test_parse_multiple_files():
    """Multiple lines → all paths returned."""
    output = (
        "?? src/tools/alpha.py\n"
        " M src/routes/mcp.py\n"
        "A  tests/test_alpha.py\n"
    )
    result = parse_git_status(output)
    assert result == {"src/tools/alpha.py", "src/routes/mcp.py", "tests/test_alpha.py"}


def test_parse_strips_whitespace():
    """Leading/trailing whitespace on path is stripped."""
    result = parse_git_status("?? src/tools/tool.py  \n")
    assert "src/tools/tool.py" in result


def test_parse_ignores_blank_lines():
    """Blank lines in output produce no entries."""
    result = parse_git_status("\n\n?? foo.py\n\n")
    assert result == {"foo.py"}


def test_parse_two_char_status_codes():
    """Status column is exactly 2 chars; path starts at column 3."""
    # XY<space><path> format from git status --short
    result = parse_git_status("MM src/config.py\n")
    assert "src/config.py" in result


# ---------------------------------------------------------------------------
# uncommitted_creates — cross-reference dirty paths against wave.allCreates
# ---------------------------------------------------------------------------


def test_no_overlap_returns_empty():
    """No dirty file is in allCreates → empty list (no block)."""
    dirty = {"other/file.py", "README.md"}
    creates = ["src/tools/my_tool.py", "tests/test_my_tool.py"]
    assert uncommitted_creates(dirty, creates) == []


def test_exact_match_detected():
    """A dirty path that exactly matches a Creates: entry is returned."""
    dirty = {"src/tools/my_tool.py"}
    creates = ["src/tools/my_tool.py"]
    result = uncommitted_creates(dirty, creates)
    assert result == ["src/tools/my_tool.py"]


def test_prefix_match_detected():
    """A dirty path that starts with a Creates: prefix is returned.

    Covers directory Creates: entries like 'src/tools/' that match
    'src/tools/new_tool.py'.
    """
    dirty = {"src/tools/new_tool.py"}
    creates = ["src/tools/"]
    result = uncommitted_creates(dirty, creates)
    assert result == ["src/tools/new_tool.py"]


def test_creates_prefix_match_against_dirty():
    """A Creates: path that is a prefix of a dirty path is detected."""
    dirty = {"src/routes/a2a/handler.py"}
    creates = ["src/routes/a2a"]
    result = uncommitted_creates(dirty, creates)
    assert "src/routes/a2a/handler.py" in result


def test_multiple_offenders_returned():
    """All dirty paths that overlap Creates: are returned."""
    dirty = {
        "src/tools/tool_a.py",
        "src/tools/tool_b.py",
        "tests/test_unrelated.py",
    }
    creates = ["src/tools/tool_a.py", "src/tools/tool_b.py"]
    result = uncommitted_creates(dirty, creates)
    assert sorted(result) == ["src/tools/tool_a.py", "src/tools/tool_b.py"]


def test_empty_creates_always_clean():
    """Empty allCreates → nothing to check → empty list."""
    dirty = {"src/tools/tool.py"}
    assert uncommitted_creates(dirty, []) == []


def test_empty_dirty_always_clean():
    """Clean working tree → nothing to block."""
    creates = ["src/tools/tool.py", "tests/test_tool.py"]
    assert uncommitted_creates(set(), creates) == []


def test_parse_renamed_file():
    """R  prefix (rename) → new path is extracted, not 'old -> new' string."""
    result = parse_git_status("R  old_name.py -> src/tools/new_name.py\n")
    assert "src/tools/new_name.py" in result
    # The old path and the raw arrow string must NOT appear
    assert "old_name.py" not in result
    assert "old_name.py -> src/tools/new_name.py" not in result


def test_parse_copied_file():
    """C  prefix (copy) → new path is extracted."""
    result = parse_git_status("C  src/original.py -> src/copy.py\n")
    assert "src/copy.py" in result
    assert "src/original.py" not in result


def test_parse_rename_new_path_matches_creates():
    """Renamed file's new path can be an offender against allCreates."""
    output = "R  old/path.py -> src/routes/a2a.py\n"
    dirty = parse_git_status(output)
    result = uncommitted_creates(dirty, ["src/routes/a2a.py"])
    assert result == ["src/routes/a2a.py"]


def test_harness_and_template_paths_detected():
    """The two workflow files themselves are valid Creates: candidates."""
    dirty = {
        "harness/workflows/wave-cycle.js",
        "template/.claude/workflows/wave-cycle.js",
    }
    creates = [
        "harness/workflows/wave-cycle.js",
        "template/.claude/workflows/wave-cycle.js",
    ]
    result = uncommitted_creates(dirty, creates)
    assert sorted(result) == sorted(creates)
