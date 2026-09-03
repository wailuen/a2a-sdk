"""RT-002: C-007 ``sanitize_text`` must have exactly ONE definition.

Component C-007 landed in ``agent_sdk/common/redact.py`` and
``models/content_types.py`` imports it -- but ``agent/loop.py`` kept a
byte-identical private second copy (``_CONTROL_CHAR_MAP`` +
``_sanitize_model_name``, comment block included), which is the exact
divergent-copy drift C-007 was registered to consolidate. The two could then
silently disagree on the control-char set or the length cap, and only one of
them would be fixed by a future security change.

The control-char class is load-bearing and is why a "close enough" second copy
is not acceptable: C0 (0x00-0x1F) is not sufficient. DEL (0x7F), NEL (0x85 --
a line break to many log/terminal consumers) and CSI (0x9B -- a single-byte
ANSI escape introducer equivalent to ESC '[') are all C1/DEL, so a copy written
as ``range(0x20)`` would defeat the very log/terminal-injection guard (SI-2)
the helper exists for.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_sdk.common.redact import sanitize_text

_SDK_ROOT = Path(__file__).resolve().parent.parent / "agent_sdk"
_REDACT = _SDK_ROOT / "common" / "redact.py"


def test_loop_has_no_private_sanitize_copy():
    src = (_SDK_ROOT / "agent" / "loop.py").read_text()
    code = [ln for ln in src.splitlines() if not ln.lstrip().startswith("#")]
    joined = "\n".join(code)
    assert "def _sanitize_model_name" not in joined
    assert "_CONTROL_CHAR_MAP" not in joined
    assert "from ..common.redact import sanitize_text" in joined


def test_control_char_map_defined_exactly_once_in_the_sdk():
    """A second ``dict.fromkeys([...], " ")`` control-char table anywhere under
    agent_sdk/ is a new divergent copy -- route it through sanitize_text."""
    pattern = re.compile(r"dict\.fromkeys\(\s*\[?\s*\*?\s*range\(0x20\)")
    definers = [
        path.relative_to(_SDK_ROOT.parent).as_posix()
        for path in _SDK_ROOT.rglob("*.py")
        if pattern.search(path.read_text())
    ]
    assert definers == ["agent_sdk/common/redact.py"], (
        f"control-char map must be defined only in redact.py; found in {definers}"
    )


@pytest.mark.parametrize(
    "codepoint,name",
    [(0x00, "NUL"), (0x1B, "ESC"), (0x0A, "LF"), (0x7F, "DEL"), (0x85, "NEL"), (0x9B, "CSI")],
)
def test_sanitize_text_strips_c0_del_and_c1(codepoint, name):
    out = sanitize_text(f"a{chr(codepoint)}b")
    assert out == "a b", f"{name} (0x{codepoint:02X}) survived sanitize_text: {out!r}"


def test_sanitize_text_default_cap_matches_the_deleted_copy():
    """loop.py's copy hard-coded ``s[:64]``; the shared helper's default must
    match, or moving the call sites over would have silently changed behaviour."""
    assert len(sanitize_text("x" * 200)) == 64


def test_loop_unknown_name_branches_are_sanitized():
    """The two call sites that used the private copy still sanitize, and still
    at the 64-char cap."""
    src = (_SDK_ROOT / "agent" / "loop.py").read_text()
    assert "sanitize_text(requested_name)" in src
    assert "sanitize_text(tc.name)" in src


def test_component_registry_records_c007_as_present():
    """RT-002: the registry row said ``planned`` and its prose still claimed the
    pattern "is currently inline at loop.py" and that redact.py "only masks
    secret-named keys/bearer values, not control chars" -- both false once the
    helper landed. A stale entry is what invites a third copy."""
    readme = (
        Path(__file__).resolve().parent.parent / "workspace" / "components" / "README.md"
    ).read_text()
    row = next(ln for ln in readme.splitlines() if ln.startswith("| C-007 "))
    assert "present" in row, row
    # And the description must record the landed call sites, not a plan.
    body = readme.split("**C-007 ")[1].split("\n**C-0")[0]
    assert "LANDED" in body
    assert "agent_sdk/agent/loop.py" in body
    assert "agent_sdk/models/content_types.py" in body
