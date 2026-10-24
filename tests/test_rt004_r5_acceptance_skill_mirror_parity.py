"""RT-004 (round 5) — the acceptance SKILL.md mirror must not half-reconcile.

`.claude/skills/acceptance/SKILL.md` (the copy `/acceptance` actually runs in
this repo) and `harness/skills/acceptance/SKILL.md` (the copy seeded into agent
repos) are a mirrored pair. A wave edited both halves but reconciled only part
of each, leaving BOTH halves wrong in different places:

  - `.claude/` still passed `adminKey: <admin_key>` — the resolved admin API key
    interpolated straight into a Workflow input and therefore into harness
    transcripts — and pointed `scriptPath` at `.claude/workflows/
    acceptance-api.js`, which does not exist in this repo. Running `/acceptance`
    here leaked the key into the transcript and then failed.
  - `harness/` carried the superseded pre-GH-89 "No secrets in output"
    paragraph.

So "port one half onto the other" is not the fix — it would have regressed one
of them. These tests pin byte-parity AND the security invariants, so neither
half can silently drift back.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LOCAL = REPO / ".claude" / "skills" / "acceptance" / "SKILL.md"
SEED = REPO / "harness" / "skills" / "acceptance" / "SKILL.md"


def test_the_two_halves_are_byte_identical():
    """Byte-identity is now ALSO pinned generically by
    `test_workflow_sync.py::test_skill_runtime_and_harness_copies_are_identical`,
    which "acceptance" was previously exempted from via
    DELIBERATELY_DIVERGENT_SKILLS — that exemption is what let the half-reconciled
    security fix sit here undetected. Asserted here too, deliberately: this file
    states the acceptance-specific reason the pair must not drift."""
    assert LOCAL.read_text() == SEED.read_text(), (
        f"{LOCAL.relative_to(REPO)} and {SEED.relative_to(REPO)} have diverged; "
        "diff the ENTIRE pair when either is edited"
    )


def test_neither_half_interpolates_the_resolved_admin_key():
    """GH-89 / SI-2: the key is externalised to a chmod-600 temp file and only
    its PATH is passed. `adminKey:` as a Workflow arg puts the resolved key in
    the prompt strings that land in harness transcripts."""
    for path in (LOCAL, SEED):
        text = path.read_text()
        assert "adminKey:" not in text, (
            f"{path.relative_to(REPO)} passes the resolved admin key as a Workflow "
            "arg; externalise it to a keyFile per GH-89/SI-2"
        )
        assert "keyFile:" in text, (
            f"{path.relative_to(REPO)} does not pass the externalised keyFile path"
        )
        assert "mode: 0o600" in text, (
            f"{path.relative_to(REPO)} writes the key file without chmod-600"
        )
        assert 'rm -f "$SERVICE_KEY_FILE"' in text, (
            f"{path.relative_to(REPO)} never cleans up the temp key file at teardown"
        )


def test_the_workflow_script_each_half_invokes_actually_exists():
    """The `.claude/` half pointed at a file that was never there, so the skill
    leaked the key and then failed on a missing script."""
    for path in (LOCAL, SEED):
        # Only the LIVE scriptPath — the "Path note" comment above it documents
        # the agent-repo variant, which correctly does not exist in this repo.
        live = [
            ln for ln in path.read_text().splitlines()
            if "scriptPath:" in ln and not ln.lstrip().startswith("//")
        ]
        assert len(live) == 1, (
            f"{path.relative_to(REPO)} has {len(live)} live scriptPath lines, expected 1"
        )
        match = re.search(r"`\$\{[^}]*\}([^`]+)`", live[0])
        assert match, f"{path.relative_to(REPO)} has no resolvable scriptPath"
        target = REPO / match.group(1).lstrip("/")
        assert target.is_file(), (
            f"{path.relative_to(REPO)} points scriptPath at {match.group(1)}, "
            "which does not exist in this repo"
        )


def test_the_referenced_workflow_takes_keyfile_not_adminkey():
    """Pin the caller/callee contract too — parity between the two SKILL.md
    halves is worthless if both agree on an arg the script does not read."""
    script = (REPO / "harness" / "workflows" / "acceptance-api.js").read_text()
    code = [
        ln for ln in script.splitlines() if not ln.lstrip().startswith("//")
    ]
    # GH-131/GH-229: the script reads keys off ``normalizedArgs`` (args after
    # JSON-string normalization), so accept either spelling of the args object.
    reads = re.compile(r"\b(?:args|normalizedArgs)\.keyFile\b")
    raw = re.compile(r"\b(?:args|normalizedArgs)\.adminKey\b")
    assert any(reads.search(ln) for ln in code), (
        "the workflow never reads args.keyFile"
    )
    assert not any(raw.search(ln) for ln in code), (
        "the workflow still reads args.adminKey (the raw-key contract)"
    )
