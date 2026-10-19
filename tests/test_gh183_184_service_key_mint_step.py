"""GH-183/GH-184: the skills' service-key mint step never prints the key and checks `service`."""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ["acceptance", "agent-verify"]
MESSAGE = "this SDK does not support service keys; upgrade to v0.15.0+"
SECRET = "sk-SECRET-PLAINTEXT-123"
ADMIN = "adm-SECRET-ADMIN-456"


def _dedent(b: str) -> str:
    return "\n".join(line[3:] if line.startswith("   ") else line for line in b.split("\n"))


def _blocks(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    return [_dedent(b) for b in re.findall(r"```bash\n(.*?)```", text, re.S) if "/admin/api/keys" in b]


def _block(path: Path) -> str:
    mint = [b for b in _blocks(path) if '"service\\":true' in b]
    assert len(mint) == 1, f"expected one service mint block in {path}"
    return mint[0]


def _fill(block: str) -> str:
    return (
        block.replace("<base_url>", "http://sdk.invalid")
        .replace("<BASE>", "http://sdk.invalid")
        .replace("<run-id>", "r1")
        .replace("<env>", "dev")
        .replace("<service_key_id>", "k1")
        .replace("<service_key_file>", "$KF")
    )


@pytest.mark.parametrize("name", SKILLS)
def test_mint_block_static_shape(name):
    block = _block(ROOT / "harness" / "skills" / name / "SKILL.md")
    assert re.search(r"curl [^|]*/admin/api/keys[^|]*\|\s*\\?\s*python3", block, re.S)
    assert "-o" not in block.split("python3")[0]
    assert '"service") is True' in block
    assert MESSAGE in block
    assert "umask 077" in block and "0o600" in block
    assert "print(d[\"key_id\"]" in block
    assert "print(d[\"plaintext\"])" not in block
    assert "echo" not in block
    assert 'Bearer %s' in block and "$ADMIN_KEY" in block
    assert "export SERVICE_KEY_FILE=" in block and "export ADMIN_KEY=" in block


TEMPLATE = ROOT / "template"
_LIVE_SCRIPT = (
    "  scriptPath: `${require('child_process').execSync('git rev-parse --show-toplevel')"
    ".toString().trim()}/%s/acceptance-api.js`,\n"
)


def _expected_template(name: str) -> str:
    """The template copy is the harness copy with ONE allowed difference.

    Agent repos (seeded from template/) ship the workflow at `.claude/workflows/`, not
    `harness/workflows/`, so the acceptance skill's live scriptPath must point there.
    Every other byte must match harness. Syncing by whole-file copy erases this line
    (and then `/acceptance` fails in every agent repo), so the allow-list is pinned here.
    """
    text = (ROOT / "harness" / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
    if name != "acceptance":
        return text
    harness_line = _LIVE_SCRIPT % "harness/workflows"
    assert text.count(harness_line) == 1, "harness acceptance skill must have one live harness scriptPath"
    return text.replace(harness_line, _LIVE_SCRIPT % ".claude/workflows")


def _template_git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(TEMPLATE), *args], capture_output=True, text=True)


def _require_template() -> None:
    # LRN-162/174/325: a missing peer checkout is a visible XFAIL, never a silent pass.
    if not (TEMPLATE / ".git").exists():
        pytest.xfail("template/ peer repo not checked out; the template mirror is unverified")


@pytest.mark.parametrize("name", SKILLS)
def test_template_skill_differs_from_harness_only_by_allowed_line(name):
    _require_template()
    got = (TEMPLATE / ".claude" / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
    assert got == _expected_template(name), (
        f"template/.claude/skills/{name}/SKILL.md must equal harness except the "
        "acceptance live scriptPath, which must point at .claude/workflows/acceptance-api.js"
    )


@pytest.mark.parametrize("name", SKILLS)
def test_template_skill_is_committed_and_pushed(name):
    _require_template()
    rel = f".claude/skills/{name}/SKILL.md"
    dirty = _template_git("status", "--porcelain", "--", rel)
    assert dirty.returncode == 0, dirty.stderr
    assert dirty.stdout.strip() == "", f"template/{rel} has uncommitted changes; commit and push them"
    ahead = _template_git("rev-list", "--count", "@{upstream}..HEAD")
    assert ahead.returncode == 0, ahead.stderr  # no upstream = cannot prove it is pushed
    assert ahead.stdout.strip() == "0", "template/ has unpushed commits; run git -C template push"
    published = _template_git("show", f"@{{upstream}}:{rel}")
    assert published.returncode == 0, published.stderr
    assert published.stdout == _expected_template(name), (
        f"template's pushed {rel} differs from harness beyond the allowed scriptPath line"
    )


def _run(block: str, tmp_path: Path, response: str):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "curl.log"
    fake = bindir / "curl"
    fake.write_text(
        "#!/bin/sh\n"
        'cat >/dev/null\n'
        'echo "$@" >> "$FAKE_LOG"\n'
        'case "$*" in *DELETE*) exit 0;; esac\n'
        'printf %s "$FAKE_RESPONSE"\n'
    )
    fake.chmod(0o755)
    key_file = tmp_path / "svc.key"
    admin_file = tmp_path / "admin.key"
    admin_file.write_text(ADMIN)
    adr = tmp_path / "workspace" / "adr"
    adr.mkdir(parents=True)
    (adr / "ADR-000-dev-credentials.md").write_text(
        f"---\nid: ADR-000-dev\nendpoint: http://sdk.invalid\nadmin_key: {ADMIN}\n---\nbody\n"
    )
    block = (
        _fill(block)
        .replace("<throwaway service key path>", str(key_file))
        .replace("<throwaway admin key path>", str(admin_file))
    )
    env = {
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "FAKE_RESPONSE": response,
        "FAKE_LOG": str(log),
        "TMPDIR": str(tmp_path),
    }
    proc = subprocess.run(
        ["bash", "-c", block], env=env, capture_output=True, text=True, cwd=tmp_path
    )
    made = sorted(tmp_path.glob("acc-key-*"))
    if made:
        key_file = made[0]
    return proc, key_file, log


@pytest.mark.parametrize("name", SKILLS)
def test_mint_success_prints_only_key_id(name, tmp_path):
    block = _block(ROOT / "harness" / "skills" / name / "SKILL.md")
    resp = json.dumps({"key_id": "k1", "plaintext": SECRET, "service": True})
    proc, key_file, log = _run(block, tmp_path, resp)
    assert proc.returncode == 0, proc.stderr
    expected = ["k1", str(key_file)] if name == "acceptance" else ["k1"]
    assert proc.stdout.split() == expected
    assert SECRET not in proc.stdout + proc.stderr
    assert ADMIN not in proc.stdout + proc.stderr
    assert key_file.read_text() == SECRET
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
    assert ADMIN not in log.read_text()


@pytest.mark.parametrize("name", SKILLS)
@pytest.mark.parametrize(
    "resp,revoked",
    [
        (json.dumps({"key_id": "k2", "plaintext": SECRET}), True),
        (json.dumps({"key_id": "k3", "plaintext": SECRET, "service": False}), True),
        ("<html>" + SECRET + "</html>", False),
    ],
    ids=["service-absent", "service-false", "non-json"],
)
def test_mint_failure_exits_nonzero_and_revokes(name, resp, revoked, tmp_path):
    block = _block(ROOT / "harness" / "skills" / name / "SKILL.md")
    proc, key_file, log = _run(block, tmp_path, resp)
    assert proc.returncode != 0
    assert MESSAGE in proc.stderr
    assert SECRET not in proc.stdout + proc.stderr
    assert ADMIN not in proc.stdout + proc.stderr
    assert not key_file.read_text()
    logged = log.read_text()
    assert ADMIN not in logged
    if revoked:
        assert "DELETE" in logged and "/admin/api/keys/k" in logged
    else:
        assert "DELETE" not in logged


def _skill(name: str) -> str:
    return (ROOT / "harness" / "skills" / name / "SKILL.md").read_text(encoding="utf-8")


def test_acceptance_invocation_block_does_not_unlink_key_file():
    text = _skill("acceptance")
    invocation = text[text.index("const _keyFile"):text.index("**Teardown:**")]
    assert "unlinkSync" not in invocation
    teardown = text[text.index("## Service key teardown"):text.index("## Rules")]
    assert 'rm -f "$SERVICE_KEY_FILE"' in teardown
    assert "unlinkSync" not in (ROOT / "harness" / "workflows" / "acceptance-api.js").read_text()


@pytest.mark.parametrize("name", SKILLS)
def test_no_literal_admin_key_in_argv(name):
    assert "Bearer <admin_key>" not in _skill(name)


def test_acceptance_teardown_revokes_without_argv_key(tmp_path):
    text = _skill("acceptance")
    teardown = text[text.index("## Service key teardown"):text.index("## Rules")]
    block = _dedent(re.findall(r"```bash\n(.*?)```", teardown, re.S)[0])
    kf = str(tmp_path / "svc.key")
    (tmp_path / "svc.key").write_text("x")
    proc, key_file, log = _run(block.replace("<service_key_file>", kf), tmp_path, "")
    assert proc.returncode == 0, proc.stderr
    assert not key_file.exists()
    assert ADMIN not in proc.stdout + proc.stderr + log.read_text()
    assert "DELETE" in log.read_text() and "/admin/api/keys/k1" in log.read_text()


from agent_sdk.credentials.store import CredentialStore  # noqa: E402


class _MemStore(CredentialStore):
    def __init__(self):
        self.v = {}

    def get(self, ns, f):
        return self.v.get((ns, f))

    def set(self, ns, f, value):
        self.v[(ns, f)] = value

    def delete(self, ns, f):
        self.v.pop((ns, f), None)

    def list_fields(self, ns):
        return sorted(f for n, f in self.v if n == ns)

    def close(self):
        pass


def _real_banner(capsys):
    from agent_sdk.auth.api_keys import ApiKeyStore, BootstrapManager

    mgr = BootstrapManager(ApiKeyStore(_MemStore()))
    capsys.readouterr()
    mgr.arm_if_needed()
    banner = capsys.readouterr().err
    return banner, mgr._token


def test_agent_verify_bootstrap_block_hides_token_and_key(tmp_path, capsys):
    blocks = _blocks(ROOT / "harness" / "skills" / "agent-verify" / "SKILL.md")
    boot = [b for b in blocks if "X-Bootstrap-Token" in b]
    assert len(boot) == 1
    block = boot[0]
    assert "Authorization: Bearer <" not in block and "echo" not in block
    log = tmp_path / "tmp.log"
    banner, token = _real_banner(capsys)
    log.write_text(banner)
    admin_file = tmp_path / "adm"
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "curl"
    fake.write_text('#!/bin/sh\ncat >"$FAKE_STDIN"\nprintf %s "$FAKE_RESPONSE"\n')
    fake.chmod(0o755)
    stdin_log = tmp_path / "stdin"
    filled = (
        _fill(block).replace("<throwaway admin key path>", str(admin_file)).replace("<tmplog>", str(log))
    )
    env = {
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "FAKE_STDIN": str(stdin_log),
        "FAKE_RESPONSE": json.dumps({"key_id": "ka", "plaintext": ADMIN}),
    }
    proc = subprocess.run(["bash", "-c", filled], env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "ka"
    assert token not in proc.stdout + proc.stderr
    assert stdin_log.read_text().strip() == f"X-Bootstrap-Token: {token}"
    assert admin_file.read_text() == ADMIN
    assert stat.S_IMODE(admin_file.stat().st_mode) == 0o600


def test_acceptance_mint_key_path_is_fresh_mktemp():
    block = _block(ROOT / "harness" / "skills" / "acceptance" / "SKILL.md")
    line = next(l for l in block.splitlines() if "export SERVICE_KEY_FILE=" in l)
    assert "<run-id>" not in line and "mktemp" in line
    assert "O_NOFOLLOW" in block and "fstat" in block and "O_CREAT" not in block


def test_acceptance_mint_refuses_foreign_mode_file(tmp_path):
    block = _block(ROOT / "harness" / "skills" / "acceptance" / "SKILL.md")
    block = block.replace("umask 077", "umask 000", 1).replace(
        '"$(mktemp "${TMPDIR:-/tmp}/acc-key-XXXXXX")"',
        '"$(mktemp "${TMPDIR:-/tmp}/acc-key-XXXXXX")"; chmod 666 "$SERVICE_KEY_FILE"',
    )
    resp = json.dumps({"key_id": "k1", "plaintext": SECRET, "service": True})
    proc, key_file, _ = _run(block, tmp_path, resp)
    assert proc.returncode != 0
    assert SECRET not in proc.stdout + proc.stderr
    assert not key_file.read_text()
