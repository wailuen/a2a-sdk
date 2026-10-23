"""Executable behaviour tests for sdk-wave.js (the a2a-sdk repo's own wave runner).

Same approach as tests/test_wave_cycle_behaviour.py, whose node harness this module reuses:
the whole script runs under node with a scripted fake agent(), and the deterministic scripts
it hands to agents (PREFLIGHT_PY, ARCHIVE_GATE_PY) run for real against throwaway git repos
laid out like this repo (agent_sdk/, no src/).

These pin behaviour, not wording, so prompts can be tightened without breaking them.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from tests.test_wave_cycle_behaviour import (
    ARCH_CHECK_OK,
    ARCH_OK,
    CLEAN_PLAN,
    CLEAN_RT,
    GREEN,
    PF,
    PROTO_CLEAN,
    RED,
    SI_PLAN,
    SLICE_PLAN,
    _commit_all,
    _py,
    _repo,
    _write,
    call,
    finding,
    group,
    labels,
    logged,
    rt,
    scan_reply,
    wave,
)
from tests.test_wave_cycle_behaviour import run as _run

REPO_ROOT = Path(__file__).parent.parent
SDK = REPO_ROOT / ".claude" / "workflows" / "sdk-wave.js"

pytestmark = [
    pytest.mark.skipif(shutil.which("node") is None, reason="node not available"),
    pytest.mark.skipif(not SDK.exists(), reason="sdk-wave.js not present in this checkout"),
]

SPF = {k: v for k, v in PF.items() if k != "wrongRunnerForRepoLayout"}
SPF["scopePaths"] = ["agent_sdk/a.py"]


def sdk_wave(groups: list[dict] | None = None, deps: dict | None = None) -> dict:
    return wave(groups or [group("A", ["agent_sdk/a.py"])], deps)


def run(rules: list | None = None, *, pf: dict | None = None, wv: dict | None = None,
        args: object = None, tmp_path: Path) -> dict:
    return _run(rules, pf=pf or SPF, wv=wv or sdk_wave(), args=args, wf=SDK, tmp_path=tmp_path)


def two_groups() -> dict:
    return sdk_wave([group("A", ["agent_sdk/a.py"]), group("B", ["agent_sdk/b.py"])])


# ─── happy path, effort, prompt hygiene ───────────────────────────────────────


def test_happy_path_archives(tmp_path: Path) -> None:
    out = run(tmp_path=tmp_path)
    assert "error" not in out, out.get("error")
    r = out["result"]
    assert r["waveId"] == "w010" and not r["protocolBlocked"] and not r["archivePlanRowMissing"]
    assert r["planReviewRounds"] == 1
    assert out["phases"] == ["Parse", "Todos Redteam", "Implement", "Unit Redteam", "Phase Redteam",
                             "Protocol Audit", "Codify", "Archive"]
    assert "archive" in labels(out) and logged(out, "archived")


def test_mechanical_calls_run_at_low_effort(tmp_path: Path) -> None:
    out = run([("^rt:unit:A:", [rt(finding(1, file="agent_sdk/a.py")), CLEAN_RT])], tmp_path=tmp_path)
    for label in ["parse:preflight", "gate:unit:A:r1", "gate:pre-archive", "gate:archive-commit", "gate:archive-plan-row"]:
        assert call(out, label)["effort"] == "low", label
    for label in ["parse", "rt:todos:r1", "rt:unit:A:r1", "impl:A-1"]:
        assert call(out, label)["effort"] is None, label


def test_every_prompt_carries_shared_tree_rule_and_no_incident_tags(tmp_path: Path) -> None:
    out = run([("^rt:todos:", [SLICE_PLAN, CLEAN_PLAN]), ("^rt:unit:A:", [rt(finding(1)), CLEAN_RT])], tmp_path=tmp_path)
    for c in out["calls"]:
        assert c["prompt"].rstrip().endswith("`git checkout .`. Edit files in place. To inspect old content use `git show` / `git diff`."), c["label"]
        if not c["label"].startswith("codify:"):
            assert not re.search(r"\b(RT|GH|WC|LRN)-\d+", c["prompt"]), c["label"]


def test_sdk_context_reaches_implementers_and_reviewers(tmp_path: Path) -> None:
    out = run([("^rt:unit:A:", [rt(finding(1)), CLEAN_RT])], tmp_path=tmp_path)
    impl = call(out, "impl:A-1")["prompt"]
    assert "public API must not break" in impl and "mypy" in impl and "tests/<your-test-file>.py" in impl
    review = call(out, "rt:unit:A:r1")["prompt"]
    assert "within agent_sdk/" in review and "public API" in review and "placeholder returns" in review
    assert "public API stable" in call(out, "fix:unit:A:r1")["prompt"]


def test_pytest_gate_runs_the_tests_directory_with_repo_venv(tmp_path: Path) -> None:
    gate = call(run(tmp_path=tmp_path), "gate:pre-archive")["prompt"]
    assert "Run: $(test -x .venv/bin/python && echo .venv/bin/python || echo python) -m pytest -q tests/" in gate


# ─── Parse / preflight ────────────────────────────────────────────────────────


@pytest.mark.parametrize("bad", [None, dict(SPF, ok=False, error="git broke"), {k: v for k, v in SPF.items() if k != "lrnNext"},
                                 dict(SPF, otherActiveWaves=None), dict(SPF, completedFileExists="no")])
def test_untrustworthy_preflight_stops_before_parse(tmp_path: Path, bad: dict | None) -> None:
    out = run([("^parse:preflight", [bad])], tmp_path=tmp_path)
    assert out["result"]["error"] == "preflight-failed" and "parse" not in labels(out)


@pytest.mark.parametrize("pf_patch,error", [
    ({"completedFileExists": True}, "wave-id-collision"),
    ({"otherActiveWaves": ["w009-y.md"], "dirtyPathCount": 3}, "concurrent-wave-uncommitted"),
    ({"otherActiveWaves": ["w009-y.md"], "dirtyPathCount": -1}, "concurrent-wave-uncommitted"),
    ({"behindCount": 2}, "behind-origin"),
])
def test_preflight_guards_abort_before_parse(tmp_path: Path, pf_patch: dict, error: str) -> None:
    out = run(pf=dict(SPF, **pf_patch), tmp_path=tmp_path)
    assert out["result"]["error"] == error and labels(out) == ["parse:preflight"]


def test_sdk_layout_is_not_a_wrong_runner(tmp_path: Path) -> None:
    # sdk-wave.js is the runner for an agent_sdk/-without-src/ repo; it never aborts on that layout.
    out = run(pf=dict(SPF, wrongRunnerForRepoLayout=True), tmp_path=tmp_path)
    assert "error" not in out["result"]


def test_scan_path_missed_by_parse_aborts(tmp_path: Path) -> None:
    out = run(pf=dict(SPF, scopePaths=["agent_sdk/a.py", "pyproject.toml"]), tmp_path=tmp_path)
    assert out["result"]["error"] == "scope-scan-mismatch" and out["result"]["missed"] == ["pyproject.toml"]


def test_empty_scope_aborts(tmp_path: Path) -> None:
    out = run(pf=dict(SPF, scopePaths=[]), wv=sdk_wave([group("A", [])]), tmp_path=tmp_path)
    assert out["result"]["error"] == "empty-scope"


def test_parse_prompt_reads_bare_and_clause_paths(tmp_path: Path) -> None:
    prompt = call(run(tmp_path=tmp_path), "parse")["prompt"]
    assert "backticked OR BARE" in prompt and "(modifies `a`, `b`)" in prompt and "**Creates:**" in prompt


def test_template_deliverable_without_checkout_aborts_before_review(tmp_path: Path) -> None:
    wv = sdk_wave([group("A", ["harness/workflows/x.js", "template/.claude/workflows/x.js"])])
    out = run(pf=dict(SPF, scopePaths=["harness/workflows/x.js"]), wv=wv, tmp_path=tmp_path)
    assert out["result"]["error"] == "template-dir-missing"
    assert not any(l.startswith("rt:") for l in labels(out))


# ─── Todos Redteam: zero issues, debug from round 4, 8-round ceiling ──────────


def test_slice_issue_fixed_by_planner_then_wave_is_reread(tmp_path: Path) -> None:
    out = run([("^rt:todos:", [SLICE_PLAN, CLEAN_PLAN])], tmp_path=tmp_path)
    assert call(out, "plan:fix:r1")["agentType"] == "planner"
    ls = labels(out)
    assert ls.index("rt:todos:r2") < ls.index("parse:replan") < ls.index("impl:A-1")


def test_annotation_only_issues_use_cheap_writer(tmp_path: Path) -> None:
    out = run([("^rt:todos:", [SI_PLAN, CLEAN_PLAN])], tmp_path=tmp_path)
    assert call(out, "plan:annotate:r1")["effort"] == "low" and "plan:fix:r1" not in labels(out)


def test_peer_repo_gap_is_an_issue_and_reaches_the_writer(tmp_path: Path) -> None:
    peer = dict(CLEAN_PLAN, issuesFound=True, peerRepoAnnotations=[
        {"todoId": "A-1", "mirrorPath": "template/.claude/workflows/x.js", "note": "n"}])
    out = run([("^rt:todos:", [peer, CLEAN_PLAN])], tmp_path=tmp_path)
    assert "template/.claude/workflows/x.js" in call(out, "plan:annotate:r1")["prompt"]
    assert logged(out, "peer-repo 1")
    review = call(out, "rt:todos:r1")["prompt"]
    assert "template/.claude/workflows/<file>.js" in review and "harness/workflows/<file>.js" in review
    assert ".claude/reference/sdk-security-invariants.md" in review


def test_debug_takes_over_from_round_four(tmp_path: Path) -> None:
    out = run([("^rt:todos:", [SLICE_PLAN] * 4 + [CLEAN_PLAN])], tmp_path=tmp_path)
    assert [l for l in labels(out) if l.startswith(("plan:", "debug:todos"))] == ["plan:fix:r1", "plan:fix:r2", "plan:fix:r3", "debug:todos:r4"]
    assert call(out, "debug:todos:r4")["agentType"] == "debug" and "error" not in out["result"]


def test_plan_never_clean_blocks_wave_after_eight_rounds(tmp_path: Path) -> None:
    out = run([("^rt:todos:", [SLICE_PLAN])], tmp_path=tmp_path)
    r = out["result"]
    assert r["error"] == "plan-review-blocked" and r["planReviewRounds"] == 8
    ls = labels(out)
    assert [l for l in ls if l.startswith("debug:todos")] == ["debug:todos:r%d" % n for n in range(4, 8)]
    assert "defer:todos:plan-review-blocked" in ls and not any(l.startswith("impl:") for l in ls)


def test_null_or_contradicting_review_is_never_clean(tmp_path: Path) -> None:
    out = run([("^rt:todos:", [None])], tmp_path=tmp_path)
    assert out["result"]["error"] == "plan-review-blocked" and out["result"]["openIssues"] == "unknown"
    out = run([("^rt:todos:", [dict(CLEAN_PLAN, issuesFound=True), CLEAN_PLAN])], tmp_path=tmp_path)
    assert out["result"]["planReviewRounds"] == 2


# ─── Implement ────────────────────────────────────────────────────────────────


def test_dead_implement_agent_is_retried_then_blocks(tmp_path: Path) -> None:
    out = run([("^impl:A-1$", [None]), ("^impl:A-1:retry$", ["done"])], tmp_path=tmp_path)
    assert not out["result"]["implementBlocked"]
    out = run([("^impl:A-1", [None])], tmp_path=tmp_path)
    assert out["result"]["implementBlocked"] and "archive" not in labels(out)


def test_tiers_follow_group_deps_and_cycles_are_recorded(tmp_path: Path) -> None:
    wv = sdk_wave([group("A", ["agent_sdk/a.py"]), group("B", ["agent_sdk/b.py"])], deps={"A": [], "B": ["A"]})
    ls = labels(run(pf=dict(SPF, scopePaths=[]), wv=wv, tmp_path=tmp_path))
    assert ls.index("impl:A-1") < ls.index("impl:B-1")
    wv = sdk_wave([group("A", ["agent_sdk/a.py"]), group("B", ["agent_sdk/b.py"])], deps={"A": ["B"], "B": ["A"]})
    out = run(pf=dict(SPF, scopePaths=[]), wv=wv, tmp_path=tmp_path)
    assert any(l.startswith("defer:circ-dep:") for l in labels(out)) and "impl:B-1" in labels(out)


# ─── Unit / phase redteam loops ───────────────────────────────────────────────


def test_severity_floor_and_medium_low_note(tmp_path: Path) -> None:
    out = run([("^rt:unit:A:", [rt(finding(1, "low"), finding(2, "medium"))])], tmp_path=tmp_path)
    assert "fix:unit:A:r1" not in labels(out) and "defer:unit:A:medium-low" in labels(out)
    assert not out["result"]["protocolBlocked"]


def test_fix_batched_below_threshold_and_per_file_above(tmp_path: Path) -> None:
    out = run([("^rt:unit:A:", [rt(finding(1), finding(2, file="agent_sdk/b.py")), CLEAN_RT])], tmp_path=tmp_path)
    assert [l for l in labels(out) if l.startswith("fix:unit:A:r1")] == ["fix:unit:A:r1"]
    many = rt(*[finding(n, file="agent_sdk/f%d.py" % n) for n in range(7)])
    out = run([("^rt:unit:A:", [many, CLEAN_RT])], tmp_path=tmp_path)
    assert len([l for l in labels(out) if l.startswith("fix:unit:A:r1:")]) == 7


def test_unit_debug_replaces_fix_at_round_four_and_budget_blocks_at_five(tmp_path: Path) -> None:
    out = run([("^rt:unit:A:", [rt(finding(n)) for n in range(1, 6)])], tmp_path=tmp_path)
    ls = labels(out)
    assert [l for l in ls if l.startswith(("fix:unit", "debug:unit"))] == ["fix:unit:A:r1", "fix:unit:A:r2", "fix:unit:A:r3", "debug:unit:A:r4"]
    assert "problem 5" in call(out, "defer:unit:A:budget-exhausted")["prompt"]
    assert any(l.startswith("codify:LRN-007") for l in ls)  # surviving findings still reach Codify
    r = out["result"]
    assert r["unitBudgetBlocked"] and r["protocolBlocked"] and "archive" not in ls
    assert logged(out, "unit redteam round budget exhausted")


def test_stall_escalates_to_debug_early(tmp_path: Path) -> None:
    out = run([("^rt:unit:A:", [rt(finding(1)), rt(finding(1)), CLEAN_RT])], tmp_path=tmp_path)
    assert "debug:unit:A:r2" in labels(out) and "fix:unit:A:r2" not in labels(out)


@pytest.mark.parametrize("bad,note", [
    (None, "rt-null-budget"),
    ({"findingsCount": 2, "findings": [finding(1)]}, "rt-mismatch-budget"),
    ({"findingsCount": 3, "findings": []}, "rt-mismatch-budget"),
    ({"findingsCount": 0, "findings": [finding(1)]}, "rt-mismatch-budget"),
])
def test_untrustworthy_review_every_round_blocks_as_unknown(tmp_path: Path, bad: dict | None, note: str) -> None:
    out = run([("^rt:unit:A:", [bad])], tmp_path=tmp_path)
    assert len([l for l in labels(out) if l.startswith("rt:unit:A:")]) == 5
    assert "defer:unit:A:" + note in labels(out)
    r = out["result"]
    assert r["redteamUnknownBlocked"] and r["protocolBlocked"] and logged(out, "never returned a trustworthy verdict")


@pytest.mark.parametrize("gates,note", [([None], "defer:unit:A:gate-null:r1"), ([RED, RED], "defer:unit:A:tests-red:r1")])
def test_gate_failure_stops_loop_and_blocks(tmp_path: Path, gates: list, note: str) -> None:
    out = run([("^rt:unit:A:", [rt(finding(1), finding(2, "low"))]), ("^gate:unit:", gates)], tmp_path=tmp_path)
    ls = labels(out)
    assert note in ls and "defer:unit:A:medium-low" in ls  # medium/low note written on this exit too
    assert out["result"]["fixLoopTestsBlocked"] and "archive" not in ls


def test_red_gate_fixed_by_test_fix_continues(tmp_path: Path) -> None:
    out = run([("^rt:unit:A:", [rt(finding(1)), CLEAN_RT]), ("^gate:unit:A:r1$", [RED]), ("^gate:unit:A:r1:recheck$", [GREEN])], tmp_path=tmp_path)
    assert "fix:tests:unit:A:r1" in labels(out) and not out["result"]["protocolBlocked"]


def test_groups_review_concurrently_and_crash_is_unknown(tmp_path: Path) -> None:
    out = run(pf=dict(SPF, scopePaths=[]), wv=two_groups(), tmp_path=tmp_path)
    assert logged(out, "2 groups concurrently")
    out = run([("^rt:unit:B:", ["__THROW__"])], pf=dict(SPF, scopePaths=[]), wv=two_groups(), tmp_path=tmp_path)
    assert out["result"]["redteamUnknownBlocked"]


def test_phase_redteam_runs_for_many_groups_with_eight_round_budget(tmp_path: Path) -> None:
    assert not any(l.startswith("rt:phase") for l in labels(run(tmp_path=tmp_path)))
    out = run([("^rt:phase:", [rt(finding(n)) for n in range(1, 9)])], pf=dict(SPF, scopePaths=[]), wv=two_groups(), tmp_path=tmp_path)
    r = out["result"]
    assert r["phaseRedteamRounds"] == 8 and r["exhausted"] and r["phaseBudgetBlocked"]
    assert [l for l in labels(out) if l.startswith("debug:phase")] == ["debug:phase:r%d" % n for n in range(4, 8)]
    assert "problem 8" in call(out, "defer:phase:budget-exhausted")["prompt"]
    assert logged(out, "phase redteam round budget exhausted")


@pytest.mark.parametrize("bad,note", [(None, "rt-null-budget"), ({"findingsCount": 1, "findings": []}, "rt-mismatch-budget")])
def test_phase_unknown_every_round_blocks(tmp_path: Path, bad: dict | None, note: str) -> None:
    out = run([("^rt:phase:", [bad])], pf=dict(SPF, scopePaths=[]), wv=two_groups(), tmp_path=tmp_path)
    assert "defer:phase:" + note in labels(out) and out["result"]["redteamUnknownBlocked"]


# ─── Protocol audit ───────────────────────────────────────────────────────────


def _proto(path: str) -> dict:
    return dict(pf=dict(SPF, scopePaths=[]), wv=sdk_wave([group("A", [path])]))


def test_protocol_legs_follow_agent_sdk_scope(tmp_path: Path) -> None:
    ls = labels(run(**_proto("agent_sdk/routes/mcp.py"), tmp_path=tmp_path))
    assert "proto:mcp" in ls and "proto:seam" in ls and "proto:a2a" not in ls
    ls = labels(run(**_proto("agent_sdk/auth/identity.py"), tmp_path=tmp_path))
    assert {"proto:a2a", "proto:mcp", "proto:agui", "proto:seam"} <= set(ls) and "proto:a2ui" not in ls
    ls = labels(run(**_proto("agent_sdk/models/content_types.py"), tmp_path=tmp_path))
    assert "proto:a2ui" in ls and "proto:mcp" not in ls
    assert not any(l.startswith("proto:") for l in labels(run(**_proto("src/routes/mcp.py"), tmp_path=tmp_path)))


def test_mcp_leg_checks_version_gating(tmp_path: Path) -> None:
    prompt = call(run(**_proto("agent_sdk/routes/mcp.py"), tmp_path=tmp_path), "proto:mcp")["prompt"]
    assert "serverInfo.title version gating" in prompt and "SUPPORTED_PROTOCOL_VERSIONS" in prompt


@pytest.mark.parametrize("label", ["^proto:mcp$", "^proto:seam$"])
def test_null_advisor_blocks(tmp_path: Path, label: str) -> None:
    out = run([(label, [None])], **_proto("agent_sdk/routes/mcp.py"), tmp_path=tmp_path)
    assert out["result"]["protocolBlocked"] and "archive" not in labels(out)


def test_critical_finding_fixed_rechecked_and_seam_always_full_scope(tmp_path: Path) -> None:
    crit = {"criticalCount": 1, "highCount": 0, "findings": [{"protocol": "MCP", "severity": "critical", "rule": "r", "description": "d"}]}
    common = dict(pf=dict(SPF, scopePaths=[]), wv=sdk_wave([group("A", ["agent_sdk/auth/middleware.py", "agent_sdk/tools.py"])]))
    out = run([("^proto:mcp$", [crit])], **common, tmp_path=tmp_path)
    ls = labels(out)
    assert ls.index("proto:fix") < ls.index("gate:proto:fix") < ls.index("proto:recheck:mcp")
    for label in ["proto:seam", "proto:recheck:seam"]:
        prompt = call(out, label)["prompt"]
        assert "agent_sdk/auth/middleware.py" in prompt and "agent_sdk/tools.py" in prompt, label
    assert not out["result"]["protocolBlocked"]
    out = run([("^proto:mcp$", [crit]), ("^proto:recheck:mcp$", [crit])], **common, tmp_path=tmp_path)
    assert out["result"]["protocolBlocked"] and "proto:defer-note" in labels(out)
    out = run([("^proto:mcp$", [crit]), ("^proto:recheck:seam$", [None])], **common, tmp_path=tmp_path)
    assert out["result"]["protocolBlocked"]
    out = run([("^proto:mcp$", [crit]), ("^gate:proto:fix", [RED])], **common, tmp_path=tmp_path)
    assert out["result"]["protocolBlocked"] and not any(l.startswith("proto:recheck") for l in labels(out))


# ─── Codify ───────────────────────────────────────────────────────────────────


def test_lrn_capture_is_capped_batched_and_numbered_from_preflight(tmp_path: Path) -> None:
    wide = rt(*[finding(n, file="agent_sdk/f%d.py" % (n % 3)) for n in range(23)])
    out = run([("^rt:unit:A:", [wide, CLEAN_RT])], tmp_path=tmp_path)
    ls = labels(out)
    assert "defer:codify:lrn-cap-exceeded" in ls
    assert [l for l in ls if l.startswith("codify:LRN")][0] == "codify:LRN-007..LRN-011"
    assert out["result"]["lrnsCaptured"] == 20


def test_sdk_scan_null_is_reported(tmp_path: Path) -> None:
    out = run([("^rt:unit:A:", [rt(finding(1)), CLEAN_RT]), ("^sdk:scan$", [None])], tmp_path=tmp_path)
    assert logged(out, "NOT classified")


# ─── Archive ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("gate", [None, RED])
def test_pre_archive_gate_must_be_green(tmp_path: Path, gate: dict | None) -> None:
    out = run([("^gate:pre-archive$", [gate])], tmp_path=tmp_path)
    assert out["result"]["testsBlockedArchive"] and "gate:archive-commit" not in labels(out) and "archive" not in labels(out)


@pytest.mark.parametrize("intent", [None, dict(ARCH_OK, ok=False, error="git broke"),
                                    {k: v for k, v in ARCH_OK.items() if k != "offendingUndeclaredScope"},
                                    {k: v for k, v in ARCH_OK.items() if k != "templateDirExists"}])
def test_untrustworthy_archive_gate_blocks_with_note(tmp_path: Path, intent: dict | None) -> None:
    out = run([("^gate:archive-commit$", [intent])], tmp_path=tmp_path)
    assert out["result"]["protocolBlocked"] and "archive" not in labels(out)
    assert "defer:archive-commit-unknown" in labels(out)


@pytest.mark.parametrize("field", ["offendingPaths", "offendingHarnessPaths", "offendingUndeclaredImports", "offendingUndeclaredScope"])
def test_each_offending_list_blocks_archive(tmp_path: Path, field: str) -> None:
    out = run([("^gate:archive-commit$", [dict(ARCH_OK, **{field: ["agent_sdk/x.py"]})])], tmp_path=tmp_path)
    assert out["result"]["protocolBlocked"] and "archive" not in labels(out) and logged(out, "agent_sdk/x.py")


def test_archive_gate_receives_full_scope(tmp_path: Path) -> None:
    assert "python3 - '[\"agent_sdk/a.py\"]' <<'ARCHIVE_GATE'" in call(run(tmp_path=tmp_path), "gate:archive-commit")["prompt"]


def test_template_deliverable_absent_at_archive_blocks_with_its_own_message(tmp_path: Path) -> None:
    wv = sdk_wave([group("A", ["harness/workflows/x.js", "template/.claude/workflows/x.js"])])
    out = run([("^gate:archive-commit$", [dict(ARCH_OK, templateDirExists=False)])],
              pf=dict(SPF, scopePaths=["harness/workflows/x.js"], templateDirExists=True), wv=wv, tmp_path=tmp_path)
    assert out["result"]["protocolBlocked"] and logged(out, "template/ absent")
    assert logged(out, "Clone wailuen/a2a-agent-template into template/")


def test_archive_never_overwrites_and_verifies_the_move(tmp_path: Path) -> None:
    prompt = call(run(tmp_path=tmp_path), "archive")["prompt"]
    step1 = prompt.split("\n2. ")[0]
    assert "workspace/todos/completed/w010-x.md` already exists" in step1 and "never move or overwrite" in step1
    assert "Test: says [pending]" in prompt
    missing = dict(ARCH_CHECK_OK, rowPresent=False, matchCount=0)
    out = run([("^gate:archive-plan-row", [missing, ARCH_CHECK_OK])], tmp_path=tmp_path)
    assert "archive-plan-row-repair" in labels(out) and not out["result"]["archivePlanRowMissing"]
    out = run([("^gate:archive-plan-row", [dict(ARCH_CHECK_OK, activeFileExists=True)])], tmp_path=tmp_path)
    assert out["result"]["archivePlanRowMissing"] and logged(out, "INCOMPLETE")


# ─── args and budget ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("args,msg", [({"today": "x"}, "sdk-wave: missing required arg(s): waveFile"), ("{nope", "not valid JSON"),
                                      ({"waveFile": "w", "today": "t", "agentBudget": 0}, "agentBudget must be a positive number"),
                                      ({"waveFile": "w", "today": "t", "agentBudget": "abc"}, "agentBudget must be a positive number")])
def test_bad_args_fail_fast(tmp_path: Path, args: object, msg: str) -> None:
    out = run(args=args, tmp_path=tmp_path)
    assert msg in out["error"] and out["calls"] == []


def test_string_args_are_parsed(tmp_path: Path) -> None:
    out = run(args=json.dumps({"waveFile": "workspace/todos/active/w010-x.md", "today": "2026-10-20"}), tmp_path=tmp_path)
    assert out["result"]["waveId"] == "w010"


def test_budget_scales_with_group_count_and_names_this_runner(tmp_path: Path) -> None:
    wv = sdk_wave([group(g, ["agent_sdk/%s.py" % g]) for g in "ABCDE"])
    assert logged(run(pf=dict(SPF, scopePaths=[]), wv=wv, tmp_path=tmp_path), "agent budget=305")
    out = run(args={"waveFile": "workspace/todos/active/w010-x.md", "today": "t", "agentBudget": 3}, tmp_path=tmp_path)
    assert "agent-call budget exceeded" in out["error"]
    assert "launches sdk-wave.js" in call(out, "defer:agent-budget-exceeded")["prompt"]


# ─── deterministic scripts, run for real against an SDK-layout repo ───────────


def _script(name: str) -> str:
    import subprocess

    src = SDK.read_text(encoding="utf-8")
    m = re.search(r"const " + name + r" = (\[.*?\n\])\.join\('\\n'\)", src, re.S)
    assert m, name + " not found"
    return subprocess.run(["node", "-e", "process.stdout.write(" + m.group(1) + ".join('\\n'))"],
                          capture_output=True, text=True, check=True).stdout


def _sdk_repo(tmp_path: Path) -> Path:
    repo = _repo(tmp_path / "sdk")
    _write(repo, "agent_sdk/__init__.py")
    _write(repo, "agent_sdk/routes/__init__.py")
    _write(repo, "agent_sdk/routes/a2a.py", "x = 1\n")
    _write(repo, "agent_sdk/credentials/__init__.py")
    _write(repo, "agent_sdk/credentials/forwarding.py")
    _write(repo, "agent_sdk/common/__init__.py")
    _write(repo, "agent_sdk/config.py")
    _write(repo, "pyproject.toml", "[project]\n")
    _commit_all(repo)
    return repo


def _gate(repo: Path, scope: list[str]) -> dict:
    return _py(_script("ARCHIVE_GATE_PY"), repo, json.dumps(scope))


def test_preflight_script_reports_sdk_repo_facts(tmp_path: Path) -> None:
    repo = _sdk_repo(tmp_path)
    _write(repo, "workspace/todos/active/w010-x.md", "x")
    _write(repo, "workspace/todos/active/CHECKPOINT-w009.md", "c")
    _write(repo, "workspace/learning/README.md", "| LRN-140 | x |")
    _commit_all(repo)
    out = _py(_script("PREFLIGHT_PY"), repo, "workspace/todos/active/w010-x.md")
    assert out == {"ok": True, "error": "", "completedFileExists": False, "templateDirExists": False,
                   "otherActiveWaves": [], "dirtyPathCount": 0, "behindCount": 0, "lrnNext": 141}


def test_scope_scan_script_reads_bare_paths(tmp_path: Path) -> None:
    w = tmp_path / "w.md"
    w.write_text("- Creates: (modifies agent_sdk/routes/mcp.py, `pyproject.toml`); adds tests/test_x.py, agent_sdk/\n")
    out = _py(_script("SCOPE_SCAN_PY"), tmp_path, str(w))
    assert out == ["agent_sdk/routes/mcp.py", "pyproject.toml", "tests/test_x.py"]


def test_archive_gate_clean_tree(tmp_path: Path) -> None:
    out = _gate(_sdk_repo(tmp_path), ["agent_sdk/routes/a2a.py"])
    assert out == {"ok": True, "error": "", "dirtyPaths": [], "offendingPaths": [], "offendingHarnessPaths": [],
                   "offendingUndeclaredImports": [], "offendingUndeclaredScope": [], "templateDirExists": False}


def test_archive_gate_flags_uncommitted_scope_and_harness_files(tmp_path: Path) -> None:
    repo = _sdk_repo(tmp_path)
    _write(repo, "agent_sdk/routes/a2a.py", "x = 2\n")
    for rel in ["tests/test_a2a.py", "docs/notes.md", "harness/skills/wave/SKILL.md", ".claude/workflows/sdk-wave.js"]:
        _write(repo, rel)
    _write(repo, "pyproject.toml", "[project]\nname='x'\n")
    out = _gate(repo, ["agent_sdk/routes/a2a.py"])
    assert out["offendingPaths"] == ["agent_sdk/routes/a2a.py"]
    assert sorted(out["offendingHarnessPaths"]) == [".claude/workflows/sdk-wave.js", "docs/notes.md",
                                                   "harness/skills/wave/SKILL.md", "pyproject.toml", "tests/test_a2a.py"]


@pytest.mark.parametrize("import_line,extracted", [
    ("from ..common.origin import guard_origin", "agent_sdk/common/origin.py"),        # relative, symbol from module
    ("from ..common import origin", "agent_sdk/common/origin.py"),                     # relative, submodule
    ("from ..common import newsubpkg", "agent_sdk/common/newsubpkg/__init__.py"),      # relative, sub-package
    ("from agent_sdk.common.origin import guard_origin", "agent_sdk/common/origin.py"),  # absolute, symbol from module
    ("from agent_sdk.common import origin", "agent_sdk/common/origin.py"),             # absolute, submodule
    ("import agent_sdk.common.origin", "agent_sdk/common/origin.py"),                  # absolute, direct
    ("import agent_sdk.newtop", "agent_sdk/newtop.py"),                                # absolute, single segment
    ("from agent_sdk import newtop", "agent_sdk/newtop.py"),                           # bare top-level
])
def test_archive_gate_finds_untracked_imported_modules(tmp_path: Path, import_line: str, extracted: str) -> None:
    repo = _sdk_repo(tmp_path)
    _write(repo, extracted, "def guard_origin(): pass\n")
    _write(repo, "agent_sdk/routes/a2a.py", import_line + "\n")
    assert _gate(repo, ["agent_sdk/routes/a2a.py"])["offendingUndeclaredImports"] == [extracted]
    assert _gate(repo, ["agent_sdk/routes/a2a.py", extracted])["offendingUndeclaredImports"] == []


def test_archive_gate_resolves_bare_relative_imports_to_subpackages(tmp_path: Path) -> None:
    repo = _sdk_repo(tmp_path)
    _write(repo, "agent_sdk/newpkg/__init__.py")
    _write(repo, "agent_sdk/__init__.py", "from . import newpkg\nfrom . import routes\n")
    out = _gate(repo, ["agent_sdk/__init__.py"])
    assert out["offendingUndeclaredImports"] == ["agent_sdk/newpkg/__init__.py"]


def test_archive_gate_ignores_tracked_missing_foreign_and_third_party_imports(tmp_path: Path) -> None:
    repo = _sdk_repo(tmp_path)
    _write(repo, "agent_sdk/routes/a2a.py",
           "from ..credentials import forwarding\nfrom ..nothing import here\nfrom agent_sdk import routes\n"
           "import src.tools\nimport httpx\nimport json\n")
    assert _gate(repo, ["agent_sdk/routes/a2a.py"])["offendingUndeclaredImports"] == []


def test_archive_gate_flags_undeclared_tracked_source_by_exact_match(tmp_path: Path) -> None:
    repo = _sdk_repo(tmp_path)
    _write(repo, "agent_sdk/config.py", "changed = True\n")
    assert _gate(repo, ["agent_sdk/routes/a2a.py"])["offendingUndeclaredScope"] == ["agent_sdk/config.py"]
    # A directory-shaped scope entry declares nothing below it.
    assert _gate(repo, ["agent_sdk/"])["offendingUndeclaredScope"] == ["agent_sdk/config.py"]
    assert _gate(repo, ["agent_sdk/config.py"])["offendingUndeclaredScope"] == []


def test_archive_gate_sees_nested_template_repo(tmp_path: Path) -> None:
    repo = _sdk_repo(tmp_path)
    _write(repo, ".gitignore", "template/\n")
    _commit_all(repo)
    tpl = _repo(repo / "template")
    _write(tpl, ".claude/workflows/wave-cycle.js", "a")
    _commit_all(tpl)
    out = _gate(repo, ["agent_sdk/routes/a2a.py"])
    assert out["templateDirExists"] is True
    assert any(p.startswith("template/ (unpushed or not on origin/main") for p in out["offendingHarnessPaths"])
    _write(tpl, ".claude/workflows/wave-cycle.js", "b")
    assert "template/.claude/workflows/wave-cycle.js" in _gate(repo, ["agent_sdk/routes/a2a.py"])["offendingHarnessPaths"]


def test_archive_gate_outside_git_is_not_ok(tmp_path: Path) -> None:
    (tmp_path / "plain").mkdir()
    out = _py(_script("ARCHIVE_GATE_PY"), tmp_path / "plain", "[]")
    assert out["ok"] is False and out["error"]


# ─── stale redteam findings (GH-211) ──────────────────────────────────────────


def _quoted(n: int) -> dict:
    return dict(finding(n), line=3, quote="x = 1")


def test_sdk_wave_quote_seen_present_then_gone_is_dropped_and_not_blocking(tmp_path: Path) -> None:
    out = run([("^rt:unit:A:", [rt(_quoted(1)), rt(_quoted(1))]),
               ("^stale:unit:A:", [{"ok": True, "stale": [], "present": [0]}, {"ok": True, "stale": [0], "present": []}])],
              tmp_path=tmp_path)
    assert "fix:unit:A:r2" not in labels(out) and "debug:unit:A:r2" not in labels(out)
    assert logged(out, "stale finding dropped")
    assert not out["result"]["protocolBlocked"]


def test_sdk_wave_unverifiable_round_one_quote_stays_blocking(tmp_path: Path) -> None:
    out = run([("^rt:unit:A:", [rt(_quoted(1)), CLEAN_RT]),
               ("^stale:unit:A:", [{"ok": True, "stale": [0], "present": []}])], tmp_path=tmp_path)
    assert "fix:unit:A:r1" in labels(out)
    assert logged(out, "unverifiable quote")


def test_sdk_wave_null_stale_check_keeps_every_finding(tmp_path: Path) -> None:
    out = run([("^rt:unit:A:", [rt(_quoted(1)), CLEAN_RT]), ("^stale:unit:A:", [None])], tmp_path=tmp_path)
    assert "fix:unit:A:r1" in labels(out)


def test_sdk_wave_rt_schema_requires_quote_and_line() -> None:
    text = SDK.read_text()
    block = text[text.index("const RT_SCHEMA"):text.index("const PROTO_SCHEMA")]
    req = re.search(r"required: \['id'[^\]]*\]", block).group(0)
    assert "'quote'" in req and "'line'" in req


# ─── GH-208: deliverable gate pinned against the SDK layout ───────────────────


def test_missing_creates_path_prunes_dependent_group(tmp_path: Path) -> None:
    wv = sdk_wave([group("A", ["agent_sdk/a.py"]), group("B", ["agent_sdk/b.py"])], {"A": [], "B": ["A"]})
    miss = {"ok": True, "checked": ["A", "B"], "missing": [{"label": "A", "paths": ["agent_sdk/a.py"]}]}
    out = run([("^deliv:tier1", [miss])], wv=wv, tmp_path=tmp_path)
    ls = [c["label"] for c in out["calls"]]
    assert "impl:B-1" not in ls and "defer:incomplete:A" in ls
    assert out["result"]["failedGroups"] == ["A"] and out["result"]["prunedGroups"] == ["B"]
    assert "archive" not in ls


# ─── GH-223: SDK candidate re-check + opt-in auto-filing ──────────────────────

from tests import test_wave_cycle_behaviour as _wc  # noqa: E402

_SDK_FILE = "agent_sdk/a.py"


def _sdk_run(rules, *, args, tmp_path):
    return run(rules, args=args, tmp_path=tmp_path)


def test_sdk_wave_default_files_nothing(tmp_path: Path) -> None:
    _wc.check_default_files_nothing(_sdk_run, _SDK_FILE, tmp_path)


def test_sdk_wave_fixed_in_wave_needs_prior_presence(tmp_path: Path) -> None:
    _wc.check_fixed_in_wave_needs_prior_presence(_sdk_run, _SDK_FILE, tmp_path)


def test_sdk_wave_candidate_status_fails_closed(tmp_path: Path) -> None:
    _wc.check_fail_closed_statuses(_sdk_run, _SDK_FILE, tmp_path)


def test_sdk_wave_recheck_reuses_stale_script(tmp_path: Path) -> None:
    _wc.check_recheck_reuses_stale_script(_sdk_run, _SDK_FILE, tmp_path)


def test_sdk_wave_auto_files_only_still_open(tmp_path: Path) -> None:
    _wc.check_auto_files_only_still_open(_sdk_run, _SDK_FILE, tmp_path)


def test_sdk_wave_auto_with_nothing_open_does_not_call_gh(tmp_path: Path) -> None:
    _wc.check_auto_with_nothing_open_does_not_call_gh(_sdk_run, _SDK_FILE, tmp_path)


@pytest.mark.parametrize("filed", [None, {"ok": True, "ghAvailable": False, "results": []}, {"ok": False, "ghAvailable": False, "results": []}])
def test_sdk_wave_auto_falls_back_to_file(tmp_path: Path, filed: object) -> None:
    _wc.check_auto_falls_back_to_file(_sdk_run, _SDK_FILE, tmp_path, filed)


def test_sdk_wave_quote_never_leaves_the_runner(tmp_path: Path) -> None:
    _wc.check_quote_never_leaves_the_runner(_sdk_run, _SDK_FILE, tmp_path)


def test_sdk_wave_flag_default_false_and_string_true(tmp_path: Path) -> None:
    _wc.check_flag_default_false_and_string_true(_sdk_run, _SDK_FILE, tmp_path)


def test_sdk_wave_classifier_keeps_id_and_quote(tmp_path: Path) -> None:
    _wc.check_classifier_keeps_id_and_quote(_sdk_run, _SDK_FILE, tmp_path)


def test_sdk_wave_candidate_logic_matches_wave_cycle() -> None:
    _wc.test_candidate_logic_matches_across_runners()


# ─── GH-228: final scope re-scans, owner assignment ───────────────────────────


@pytest.mark.parametrize("label", ["scan:scope:final-pre-audit", "scan:scope:final-pre-archive"])
def test_gh228_untrustworthy_final_rescan_blocks_archive(tmp_path: Path, label: str) -> None:
    out = run([("^" + label + "$", [None])], tmp_path=tmp_path)
    assert label in labels(out)
    assert out["result"]["protocolBlocked"] and "archive" not in labels(out)
    assert logged(out, "final scope re-scan returned no trustworthy result \u2014 archive BLOCKED")


def test_gh228_path_added_after_protocol_audit_reaches_archive_gate(tmp_path: Path) -> None:
    reply = scan_reply(sdk_wave(), ("agent_sdk/after_codify.py", "A-1", "modify"))
    out = run([("^scan:scope:final-pre-archive$", [reply])], tmp_path=tmp_path)
    assert "agent_sdk/after_codify.py" in call(out, "gate:archive-commit")["prompt"]


def test_gh228_unowned_new_path_blocks_wave_and_is_assigned_to_no_group(tmp_path: Path) -> None:
    reply = scan_reply(sdk_wave(), ("agent_sdk/late.py", None, "create"))
    out = run([("^scan:scope:", [reply])], tmp_path=tmp_path)
    assert logged(out, "scope re-scan: path agent_sdk/late.py has no owning todo \u2014 wave BLOCKED")
    assert not [l for l in labels(out) if l.startswith("rt:unit:")]
    assert out["result"]["protocolBlocked"] and "archive" not in labels(out)


def test_gh228_new_path_is_assigned_to_the_declaring_group(tmp_path: Path) -> None:
    wv = two_groups()
    reply = scan_reply(wv, ("agent_sdk/late.py", "B-1", "create"))
    out = run([("^scan:scope:", [reply])], wv=wv, tmp_path=tmp_path)
    assert "agent_sdk/late.py" in call(out, "rt:unit:B:r1")["prompt"]
    assert "agent_sdk/late.py" not in call(out, "rt:unit:A:r1")["prompt"]
