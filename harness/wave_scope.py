"""RT-001 (fix round): wave scope extraction helpers for wave-cycle.js's Parse phase.

wave-cycle.js's Parse-phase agent call extracts allCreates/allModifies paths from a wave
file's todos by following written prompt instructions, not by invoking this module (the
extraction runs inside an LLM agent call, not this Python process). These pure functions
are a deterministic reference implementation of the same extraction rule, mirroring the
`agent_sdk/harness/archive_guard.py` pattern for the archive gate: a real, testable spec
for an algorithm the JS prompt also describes in prose.

RT-009: this module lives under repo-level `harness/` (DESIGN.md §3: "Repo-level (not in
the wheel): template/, harness/, docs/"), not under `agent_sdk/`. It is a harness-only
reference implementation with no runtime importer — wave-cycle.js's Parse phase never
imports it, the extraction runs inside an LLM agent call — so shipping it inside the
`agent_sdk` wheel (packages = ["agent_sdk"] in pyproject.toml) would ship unreachable
public API to every downstream agent. Only `tests/test_wave_scope_extraction.py` imports
this module, from the repo's own test suite, which is why it can live outside the wheel
without losing test coverage.

Both functions are free of I/O so they are trivially unit-testable.
"""

from __future__ import annotations

import re

_BACKTICKED_TOKEN_RE = re.compile(r"`([^`]+)`")
_KEYWORD_RE = re.compile(r"\b(modifies|adds)\b", re.IGNORECASE)
_PATH_EXTENSIONS = (".py", ".js", ".ts", ".md", ".json", ".toml", ".yaml", ".yml")
_ROOT_LEVEL_EXTENSIONS = (".md", ".json", ".toml", ".yaml", ".yml")


def _looks_like_path(token: str) -> bool:
    """A backticked token counts as scope only if it names exactly ONE FILE.

    RT-006: rejecting only parens/quotes/whitespace (the pre-fix rule) let every
    dotted attribute chain, bare constant, and slash-command this repo's todos
    routinely wrap in backticks as prose — `openai.RateLimitError`, `wave.allScope`,
    `_fire`, `max_retries`, `AGENT_SDK_`, `/sdk-test` — through as if it were scope.

    RT-001 (round-7 fresh-lens debug): tightening that to "contains a slash" was
    still too loose in the one direction that matters. Creates:/Modifies: lines in
    this repo are PROSE, and prose routinely backticks a DIRECTORY to explain
    something — "(`agent_sdk/` is not a harness dir)" — or a GLOB — `agent_sdk/**.py`.
    Both passed the slash test, so an explanatory aside silently declared an entire
    subtree as in-scope. Paired with the archive gate's old
    scope-entry-is-a-directory-prefix-of-a-dirty-path rule, the single token
    `agent_sdk/` marked every dirty file under agent_sdk/ as "declared" and disabled
    the undeclared-scope gate outright. A scope entry is a claim about one
    deliverable, so only a token naming one file may become one:

    - no whitespace, parens or quotes (prose punctuation);
    - no glob metacharacter (`*`, `?`) — a pattern names a set, not a file;
    - no trailing "/" — that is a directory, not a file;
    - no leading "/" — repo-relative paths never start with one (a `/sdk-test`
      slash-command reference does);
    - the FINAL segment must look like a filename: not starting with "." (rules out
      a bare extension like `.py`) and ending in a known repo file extension;
    - a token with NO "/" additionally may not contain "__", which rules out a
      dunder attribute chain like `openai.AsyncOpenAI.__init__`. The guard is
      scoped to slash-less tokens on purpose: once a token has a directory
      segment it is unambiguously a path, and `agent_sdk/__init__.py` is a real
      and extremely common deliverable.
    - a slash-less token is further restricted to ROOT-LEVEL extensions
      (`.md`/`.json`/`.toml`/`.yaml`/`.yml`) — RT-001 (residual fix): no
      `.py`/`.js`/`.ts` source file lives bare at this repo's root, every real
      one is nested under a directory, so a bare `wave-cycle.js` or
      `test_workflow_sync.py` is never a genuine claim about the real,
      directory-qualified file — it can never string-match the dirty path
      `git status` reports for it (verified against workspace/todos/active/
      w039-gh-issues.md's GH-134 item, which names `test_mcp_conformance_w9.py`
      bare with no fully-qualified form declared anywhere else on the wave
      file). `pyproject.toml` and friends genuinely DO live at the repo root,
      so those extensions stay eligible bare.

    Only the final segment is extension-checked, so a real path whose leading
    segment is dot-prefixed (`.claude/workflows/wave-cycle.js`) still qualifies.
    """
    if not token or any(ch in token for ch in " ()\"'"):
        return False
    if "*" in token or "?" in token:
        return False
    if token.startswith("/") or token.endswith("/"):
        return False
    final_segment = token.rsplit("/", 1)[-1]
    if final_segment.startswith("."):
        return False
    if "/" not in token:
        if "__" in token:
            return False
        return final_segment.endswith(_ROOT_LEVEL_EXTENSIONS)
    return final_segment.endswith(_PATH_EXTENSIONS)


def extract_scope_paths(line: str) -> tuple[list[str], list[str]]:
    """Extract every backticked path token from one todo's Creates:/Modifies: line.

    RT-001 (fix round): the dominant form in this repo's todos puts every real
    deliverable inside prose, not a bare path list — e.g. a Creates: line reading
    ``Creates: (modifies `a`, `b`, `c`); adds `d`, `e``` — with no separate
    ``Modifies:`` field at all. Every backticked path-shaped token on the line is
    extracted regardless of position, by tracking which of the two keywords
    ("modifies" / "adds") most recently preceded it — a parenthetical
    ``(modifies ...)`` clause or a bare ``modifies `path``` clause both open a MODIFY
    span that lasts until the next keyword (whichever comes first), and a trailing
    "adds ..." clause re-opens a CREATE span the same way. A token before the first
    keyword on the line falls back to the field the line itself declares (Creates:
    or Modifies:).

    Args:
        line: One raw ``Creates:``/``Modifies:`` line from a todo body.

    Returns:
        (creates, modifies) — backticked path tokens sorted into each bucket, in the
        order they appear on the line.
    """
    field_is_modifies = bool(re.match(r"\s*Modifies:", line, re.IGNORECASE))
    default_label = "modify" if field_is_modifies else "create"

    keywords = [(m.start(), m.group(1).lower()) for m in _KEYWORD_RE.finditer(line)]

    def _label_at(pos: int) -> str:
        label = default_label
        for kw_pos, kw in keywords:
            if kw_pos > pos:
                break
            label = "modify" if kw == "modifies" else "create"
        return label

    creates: list[str] = []
    modifies: list[str] = []
    for m in _BACKTICKED_TOKEN_RE.finditer(line):
        token = m.group(1)
        if not _looks_like_path(token):
            continue
        (modifies if _label_at(m.start()) == "modify" else creates).append(token)
    return creates, modifies


def extract_wave_scope(todo_text: str) -> tuple[list[str], list[str]]:
    """Scan every Creates:/Modifies: line in a wave file's todo bodies.

    Args:
        todo_text: Full text of a wave markdown file.

    Returns:
        (allCreates, allModifies) — every backticked path token found, in file order.
        Callers that need wave.allScope should take the union, e.g.
        ``set(all_creates) | set(all_modifies)``.
    """
    all_creates: list[str] = []
    all_modifies: list[str] = []
    for raw_line in todo_text.splitlines():
        line = raw_line.strip()
        if line.startswith(("- Creates:", "Creates:")):
            creates, modifies = extract_scope_paths(line)
            all_creates.extend(creates)
            all_modifies.extend(modifies)
        elif line.startswith(("- Modifies:", "Modifies:")):
            # RT-003: both buckets, exactly as the Creates: branch above.
            # extract_scope_paths() returns two buckets because ONE line can carry
            # both spans — a `Modifies:` line ending in "; adds `c/d.py`" opens a
            # CREATE span. Discarding the creates bucket here dropped every such
            # path out of allScope entirely, so a file created by that todo never
            # reached review scope, protocol-surface classification, or the archive
            # commit check.
            creates, modifies = extract_scope_paths(line)
            all_creates.extend(creates)
            all_modifies.extend(modifies)
    return all_creates, all_modifies
