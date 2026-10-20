"""Executable behaviour tests for wave-cycle.js (the downstream-agent wave runner).

The whole workflow script runs under node with a scripted fake agent(): each test lists
the responses agents give (by label) and asserts on what the runner does — which agents
it dispatches, with which agentType/effort, what it returns, and what it blocks. The two
deterministic scripts the runner hands to agents (PREFLIGHT_PY, ARCHIVE_GATE_PY) are run
for real against throwaway git repositories.

These pin behaviour, not wording, so prompts can be tightened without breaking them.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
WAVE_CYCLE_COPIES = [
    p
    for p in [
        REPO_ROOT / "harness" / "workflows" / "wave-cycle.js",
        REPO_ROOT / ".claude" / "workflows" / "wave-cycle.js",
        REPO_ROOT / "template" / ".claude" / "workflows" / "wave-cycle.js",
    ]
    if p.exists()
]
WC = WAVE_CYCLE_COPIES[0]

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not available")

# ─── fake workflow runtime ────────────────────────────────────────────────────

_RUNNER = r"""
const fs = require('fs')
const wfPath = process.argv[2], scenarioPath = process.argv[3]
const scenario = JSON.parse(fs.readFileSync(scenarioPath, 'utf8'))
const calls = [], logs = [], phases = [], counters = {}
function respond(label) {
  for (const rule of scenario.rules) {
    if (new RegExp(rule.match).test(label)) {
      const n = counters[rule.match] = (counters[rule.match] || 0) + 1
      const r = rule.responses[Math.min(n, rule.responses.length) - 1]
      if (r === '__THROW__') throw new Error('agent crashed')
      return JSON.parse(JSON.stringify(r))
    }
  }
  throw new Error('no scripted response for label ' + label)
}
global.agent = async function(prompt, opts) {
  opts = opts || {}
  calls.push({ label: opts.label || '', agentType: opts.agentType || null, effort: opts.effort || null, prompt: prompt })
  return respond(opts.label || '')
}
global.parallel = async function(thunks) {
  return Promise.all(thunks.map(function(t) { return Promise.resolve().then(t).catch(function() { return null }) }))
}
global.phase = function(t) { phases.push(t) }
global.log = function(m) { logs.push(String(m)) }
global.args = scenario.args
const body = fs.readFileSync(wfPath, 'utf8').replace(/^export const meta/m, 'const meta')
const AsyncFunction = Object.getPrototypeOf(async function() {}).constructor
const out = function(extra) {
  process.stdout.write(JSON.stringify(Object.assign({ calls: calls, logs: logs, phases: phases }, extra)))
}
new AsyncFunction(body)().then(function(result) { out({ result: result }) },
                               function(e) { out({ error: String(e && e.message || e) }) })
"""

PF = {
    "ok": True, "error": "", "wrongRunnerForRepoLayout": False, "completedFileExists": False,
    "templateDirExists": False, "otherActiveWaves": [], "dirtyPathCount": 0, "behindCount": 0,
    "lrnNext": 7, "scopePaths": ["src/tools/a.py"],
}


def todo(tid: str) -> dict:
    return {"id": tid, "title": "t " + tid, "body": "body of " + tid}


def group(label: str, creates: list[str], todos: list[str] | None = None) -> dict:
    return {"label": label, "creates": creates, "modifies": [], "todos": [todo(t) for t in (todos or [label + "-1"])]}


def wave(groups: list[dict] | None = None, deps: dict | None = None) -> dict:
    groups = groups or [group("A", ["src/tools/a.py"])]
    creates = sorted({p for g in groups for p in g["creates"]})
    return {
        "waveId": "w010", "allCreates": creates, "allModifies": [],
        "groupDeps": deps or {g["label"]: [] for g in groups}, "groups": groups,
    }


CLEAN_PLAN = {"issuesFound": False, "reuseAnnotations": [], "siAnnotations": [], "sliceIssues": [],
              "newCandidates": [], "peerRepoAnnotations": []}
SLICE_PLAN = dict(CLEAN_PLAN, issuesFound=True, sliceIssues=[{"todoId": "A-1", "issue": "horizontal layer"}])
SI_PLAN = dict(CLEAN_PLAN, issuesFound=True, siAnnotations=[{"todoId": "A-1", "siId": "SI-1", "note": "n"}])
CLEAN_RT = {"findingsCount": 0, "findings": []}
GREEN = {"exitCode": 0, "passCount": 10, "failCount": 0, "failures": []}
RED = {"exitCode": 1, "passCount": 9, "failCount": 1, "failures": ["tests/test_a.py::test_x: boom"]}
ARCH_OK = {"ok": True, "error": "", "dirtyPaths": [], "offendingPaths": [], "offendingHarnessPaths": [],
           "offendingUndeclaredImports": [], "offendingUndeclaredScope": [], "templateDirExists": False}
ARCH_CHECK_OK = {"rowPresent": True, "matchCount": 1, "archivedFileExists": True, "activeFileExists": False}
PROTO_CLEAN = {"criticalCount": 0, "highCount": 0, "findings": []}


def finding(n: int, severity: str = "high", file: str = "src/tools/a.py") -> dict:
    return {"id": "F%d" % n, "severity": severity, "file": file, "description": "problem %d" % n,
            "fix": "fix it", "codify": "lesson"}


def rt(*findings: dict) -> dict:
    return {"findingsCount": len(findings), "findings": list(findings)}


def run(rules: list | None = None, *, pf: dict | None = None, wv: dict | None = None,
        args: object = None, wf: Path = WC, tmp_path: Path) -> dict:
    defaults = [
        ("^parse:preflight", [pf or PF]),
        ("^parse(:replan)?$", [wv or wave()]),
        ("^rt:todos:", [CLEAN_PLAN]),
        ("^rt:", [CLEAN_RT]),
        ("^gate:archive-commit$", [ARCH_OK]),
        ("^gate:archive-plan-row", [ARCH_CHECK_OK]),
        ("^gate:", [GREEN]),
        ("^proto:(a2a|mcp|agui|a2ui|seam|recheck)", [PROTO_CLEAN]),
        ("^sdk:scan$", [{"sdkCandidates": []}]),
        (".*", ["done"]),
    ]
    scenario = {
        "args": args if args is not None else {"waveFile": "workspace/todos/active/w010-x.md", "today": "2026-10-20"},
        "rules": [{"match": m, "responses": r} for m, r in (rules or []) + defaults],
    }
    sc = tmp_path / "scenario.json"
    sc.write_text(json.dumps(scenario))
    runner = tmp_path / "runner.js"
    runner.write_text(_RUNNER)
    proc = subprocess.run(["node", str(runner), str(wf), str(sc)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def labels(out: dict) -> list[str]:
    return [c["label"] for c in out["calls"]]


def call(out: dict, label: str) -> dict:
    hits = [c for c in out["calls"] if c["label"] == label]
    assert hits, "no call labelled %r; calls: %s" % (label, labels(out))
    return hits[0]


def logged(out: dict, needle: str) -> bool:
    return any(needle in line for line in out["logs"])


# ─── happy path ───────────────────────────────────────────────────────────────


def test_happy_path_archives(tmp_path: Path) -> None:
    out = run(tmp_path=tmp_path)
    assert "error" not in out, out.get("error")
    r = out["result"]
    assert r["waveId"] == "w010" and not r["protocolBlocked"] and not r["archivePlanRowMissing"]
    assert r["planReviewRounds"] == 1
    assert "archive" in labels(out)
    assert out["phases"] == ["Parse", "Todos Redteam", "Implement", "Unit Redteam", "Phase Redteam",
                             "Protocol Audit", "Codify", "Archive"]
    assert "parse:replan" not in labels(out)  # no plan edits → no re-read
    assert logged(out, "archived")


def test_mechanical_calls_run_at_low_effort(tmp_path: Path) -> None:
    out = run([("^rt:unit:A:", [rt(finding(1)), CLEAN_RT])], tmp_path=tmp_path)
    for label in ["parse:preflight", "gate:unit:A:r1", "gate:pre-archive", "gate:archive-commit", "gate:archive-plan-row"]:
        assert call(out, label)["effort"] == "low", label
    # Judgment calls inherit the session effort.
    for label in ["parse", "rt:todos:r1", "rt:unit:A:r1", "impl:A-1"]:
        assert call(out, label)["effort"] is None, label


def test_every_prompt_carries_shared_tree_rule_and_no_incident_tags(tmp_path: Path) -> None:
    rules = [("^rt:todos:", [SLICE_PLAN, dict(CLEAN_PLAN, newCandidates=[{"name": "n", "location": "l", "description": "d"}])]),
             ("^rt:unit:A:", [rt(finding(1)), CLEAN_RT])]
    out = run(rules, tmp_path=tmp_path)
    for c in out["calls"]:
        assert c["prompt"].rstrip().endswith("`git checkout .`. Edit files in place. To inspect old content use `git show` / `git diff`."), c["label"]
        if not c["label"].startswith("codify:"):  # codify prompts carry the assigned LRN IDs
            assert not re.search(r"\b(RT|GH|WC|LRN)-\d+", c["prompt"]), (c["label"], re.findall(r"\b(?:RT|GH|WC|LRN)-\d+", c["prompt"]))
        assert "fresh-lens debug)" not in c["prompt"] and not re.search(r"\bw0\d\d\b", c["prompt"].replace("w010", "")), c["label"]


def test_pytest_command_prefers_repo_venv(tmp_path: Path) -> None:
    out = run(tmp_path=tmp_path)
    gate = call(out, "gate:pre-archive")["prompt"]
    assert "Run: $(test -x .venv/bin/python && echo .venv/bin/python || echo python) -m pytest -q" in gate
    assert "-m pytest -q tests/test_<specific>.py" in call(out, "impl:A-1")["prompt"]


# ─── Parse / preflight ────────────────────────────────────────────────────────


@pytest.mark.parametrize("bad", [None, dict(PF, ok=False, error="git broke"), {k: v for k, v in PF.items() if k != "lrnNext"},
                                 dict(PF, otherActiveWaves=None), dict(PF, completedFileExists="no")])
def test_untrustworthy_preflight_stops_before_parse(tmp_path: Path, bad: dict | None) -> None:
    out = run([("^parse:preflight", [bad])], tmp_path=tmp_path)
    assert out["result"]["error"] == "preflight-failed"
    assert "parse" not in labels(out)


@pytest.mark.parametrize("pf_patch,error", [
    ({"wrongRunnerForRepoLayout": True}, "wrong-runner-for-repo-layout"),
    ({"completedFileExists": True}, "wave-id-collision"),
    ({"otherActiveWaves": ["w009-y.md"], "dirtyPathCount": 3}, "concurrent-wave-uncommitted"),
    ({"otherActiveWaves": ["w009-y.md"], "dirtyPathCount": -1}, "concurrent-wave-uncommitted"),
    ({"behindCount": 2}, "behind-origin"),
])
def test_preflight_guards_abort_before_parse(tmp_path: Path, pf_patch: dict, error: str) -> None:
    out = run(pf=dict(PF, **pf_patch), tmp_path=tmp_path)
    assert out["result"]["error"] == error
    assert labels(out) == ["parse:preflight"]


def test_wrong_runner_message_names_sdk_wave(tmp_path: Path) -> None:
    out = run(pf=dict(PF, wrongRunnerForRepoLayout=True), tmp_path=tmp_path)
    assert logged(out, "sdk-wave.js") and logged(out, ".claude/skills/wave/SKILL.md")


def test_collision_names_the_completed_file(tmp_path: Path) -> None:
    out = run(pf=dict(PF, completedFileExists=True), tmp_path=tmp_path)
    assert out["result"] == {"error": "wave-id-collision", "waveId": "w010",
                             "completedFile": "workspace/todos/completed/w010-x.md"}


def test_other_active_wave_on_clean_tree_proceeds(tmp_path: Path) -> None:
    out = run(pf=dict(PF, otherActiveWaves=["w009-y.md"], dirtyPathCount=0), tmp_path=tmp_path)
    assert "error" not in out["result"]


def test_parse_null_fails(tmp_path: Path) -> None:
    out = run([("^parse$", [None])], tmp_path=tmp_path)
    assert out["result"]["error"] == "parse-failed"


def test_scan_path_missed_by_parse_aborts(tmp_path: Path) -> None:
    out = run(pf=dict(PF, scopePaths=["src/tools/a.py", "src/config.py"]), tmp_path=tmp_path)
    assert out["result"]["error"] == "scope-scan-mismatch"
    assert out["result"]["missed"] == ["src/config.py"]


def test_scan_paths_join_scope(tmp_path: Path) -> None:
    wv = wave([group("A", ["src/tools/a.py", "src/config.py"])])
    out = run(pf=dict(PF, scopePaths=["src/config.py"]), wv=wv, tmp_path=tmp_path)
    assert "src/config.py" in call(out, "rt:unit:A:r1")["prompt"]


def test_empty_scope_aborts(tmp_path: Path) -> None:
    out = run(pf=dict(PF, scopePaths=[]), wv=wave([group("A", [])]), tmp_path=tmp_path)
    assert out["result"]["error"] == "empty-scope"


def test_template_deliverable_without_checkout_aborts_before_review(tmp_path: Path) -> None:
    wv = wave([group("A", ["harness/workflows/x.js", "template/.claude/workflows/x.js"])])
    out = run(pf=dict(PF, scopePaths=["harness/workflows/x.js"]), wv=wv, tmp_path=tmp_path)
    assert out["result"]["error"] == "template-dir-missing"
    assert not any(l.startswith("rt:") for l in labels(out))
    out = run(pf=dict(PF, scopePaths=["harness/workflows/x.js"], templateDirExists=True), wv=wv, tmp_path=tmp_path)
    assert "error" not in out["result"]


# ─── Todos Redteam: zero issues, debug from round 4, 8-round ceiling ──────────


def test_slice_issue_fixed_by_planner_then_wave_is_reread(tmp_path: Path) -> None:
    out = run([("^rt:todos:", [SLICE_PLAN, CLEAN_PLAN])], tmp_path=tmp_path)
    assert call(out, "plan:fix:r1")["agentType"] == "planner"
    assert out["result"]["planReviewRounds"] == 2
    ls = labels(out)
    assert ls.index("rt:todos:r2") < ls.index("parse:preflight:replan") < ls.index("parse:replan") < ls.index("impl:A-1")
    # Round 2 review is told what round 1 found.
    assert "horizontal layer" in call(out, "rt:todos:r2")["prompt"]


def test_annotation_only_issues_use_cheap_writer(tmp_path: Path) -> None:
    out = run([("^rt:todos:", [SI_PLAN, CLEAN_PLAN])], tmp_path=tmp_path)
    c = call(out, "plan:annotate:r1")
    assert c["effort"] == "low" and c["agentType"] is None
    assert "plan:fix:r1" not in labels(out)


def test_reread_after_annotation_feeds_new_bodies_to_implementers(tmp_path: Path) -> None:
    annotated = wave()
    annotated["groups"][0]["todos"][0]["body"] = "body of A-1\nSI: SI-1  # n"
    out = run([("^rt:todos:", [SI_PLAN, CLEAN_PLAN]), ("^parse(:replan)?$", [wave(), annotated])], tmp_path=tmp_path)
    assert "SI: SI-1" in call(out, "impl:A-1")["prompt"]


def test_debug_takes_over_from_round_four(tmp_path: Path) -> None:
    out = run([("^rt:todos:", [SLICE_PLAN, SLICE_PLAN, SLICE_PLAN, SLICE_PLAN, CLEAN_PLAN])], tmp_path=tmp_path)
    ls = labels(out)
    assert [l for l in ls if l.startswith(("plan:", "debug:todos"))] == ["plan:fix:r1", "plan:fix:r2", "plan:fix:r3", "debug:todos:r4"]
    assert call(out, "debug:todos:r4")["agentType"] == "debug"
    assert out["result"]["planReviewRounds"] == 5 and "error" not in out["result"]


def test_plan_never_clean_blocks_wave_after_eight_rounds(tmp_path: Path) -> None:
    out = run([("^rt:todos:", [SLICE_PLAN])], tmp_path=tmp_path)
    r = out["result"]
    assert r["error"] == "plan-review-blocked" and r["planReviewRounds"] == 8
    assert r["openIssues"]["sliceIssues"] == SLICE_PLAN["sliceIssues"]
    ls = labels(out)
    assert len([l for l in ls if l.startswith("rt:todos:")]) == 8
    assert [l for l in ls if l.startswith("debug:todos")] == ["debug:todos:r4", "debug:todos:r5", "debug:todos:r6", "debug:todos:r7"]
    assert "defer:todos:plan-review-blocked" in ls
    assert not any(l.startswith("impl:") for l in ls)


def test_null_review_is_unknown_and_retried(tmp_path: Path) -> None:
    out = run([("^rt:todos:", [None, CLEAN_PLAN])], tmp_path=tmp_path)
    assert out["result"]["planReviewRounds"] == 2 and "error" not in out["result"]
    out = run([("^rt:todos:", [None])], tmp_path=tmp_path)
    assert out["result"]["error"] == "plan-review-blocked" and out["result"]["openIssues"] == "unknown"
    assert not any(l.startswith("impl:") for l in labels(out))


def test_self_contradicting_reviews_are_not_clean(tmp_path: Path) -> None:
    out = run([("^rt:todos:", [dict(CLEAN_PLAN, issuesFound=True), CLEAN_PLAN])], tmp_path=tmp_path)
    assert out["result"]["planReviewRounds"] == 2
    out = run([("^rt:todos:", [dict(SLICE_PLAN, issuesFound=False), CLEAN_PLAN])], tmp_path=tmp_path)
    assert "plan:fix:r1" in labels(out)


def test_new_component_candidates_are_informational_and_registered(tmp_path: Path) -> None:
    cand = dict(CLEAN_PLAN, newCandidates=[{"name": "Cache", "location": "src/common/cache.py", "description": "d"}])
    out = run([("^rt:todos:", [cand])], tmp_path=tmp_path)
    assert out["result"]["planReviewRounds"] == 1 and out["result"]["cNnnRegistered"] == 1
    assert "registry:register" in labels(out)


def test_reread_scope_with_unlandable_template_path_aborts(tmp_path: Path) -> None:
    peer = dict(CLEAN_PLAN, issuesFound=True, peerRepoAnnotations=[
        {"todoId": "A-1", "mirrorPath": "template/.claude/workflows/x.js", "note": "n"}])
    replanned = wave([group("A", ["harness/workflows/x.js", "template/.claude/workflows/x.js"])])
    out = run([("^rt:todos:", [peer, CLEAN_PLAN]), ("^parse(:replan)?$", [wave([group("A", ["harness/workflows/x.js"])]), replanned])],
              pf=dict(PF, scopePaths=["harness/workflows/x.js"]), tmp_path=tmp_path)
    assert out["result"]["error"] == "template-dir-missing"


# ─── Implement ────────────────────────────────────────────────────────────────


def test_dead_implement_agent_is_retried_then_blocks(tmp_path: Path) -> None:
    out = run([("^impl:A-1$", [None]), ("^impl:A-1:retry$", ["done"])], tmp_path=tmp_path)
    assert not out["result"]["implementBlocked"] and not out["result"]["protocolBlocked"]
    out = run([("^impl:A-1", [None])], tmp_path=tmp_path)
    assert out["result"]["implementBlocked"] and out["result"]["protocolBlocked"]
    assert "archive" not in labels(out)


def test_circular_group_deps_are_recorded_and_still_run(tmp_path: Path) -> None:
    wv = wave([group("A", ["src/a.py"]), group("B", ["src/b.py"])], deps={"A": ["B"], "B": ["A"]})
    out = run(pf=dict(PF, scopePaths=[]), wv=wv, tmp_path=tmp_path)
    assert any(l.startswith("defer:circ-dep:") for l in labels(out))
    assert "impl:A-1" in labels(out) and "impl:B-1" in labels(out)


def test_dependent_group_runs_after_its_dependency(tmp_path: Path) -> None:
    wv = wave([group("A", ["src/a.py"]), group("B", ["src/b.py"])], deps={"A": [], "B": ["A"]})
    ls = labels(run(pf=dict(PF, scopePaths=[]), wv=wv, tmp_path=tmp_path))
    assert ls.index("impl:A-1") < ls.index("impl:B-1")


# ─── Unit / phase redteam loops ───────────────────────────────────────────────


def test_unit_findings_fixed_then_clean(tmp_path: Path) -> None:
    out = run([("^rt:unit:A:", [rt(finding(1), finding(2, "low")), CLEAN_RT])], tmp_path=tmp_path)
    assert call(out, "fix:unit:A:r1")["agentType"] == "python-implementer"
    assert "defer:unit:A:medium-low" in labels(out)
    assert not out["result"]["protocolBlocked"]


def test_unit_debug_replaces_fix_at_round_four_and_budget_blocks_at_five(tmp_path: Path) -> None:
    out = run([("^rt:unit:A:", [rt(finding(n)) for n in range(1, 6)])], tmp_path=tmp_path)
    ls = labels(out)
    assert [l for l in ls if l.startswith(("fix:unit", "debug:unit"))] == [
        "fix:unit:A:r1", "fix:unit:A:r2", "fix:unit:A:r3", "debug:unit:A:r4"]
    assert "defer:unit:A:budget-exhausted" in ls
    r = out["result"]
    assert r["unitBudgetBlocked"] and r["protocolBlocked"] and "archive" not in ls
    assert logged(out, "unit redteam round budget exhausted")


def test_unit_stall_escalates_to_debug_early(tmp_path: Path) -> None:
    out = run([("^rt:unit:A:", [rt(finding(1)), rt(finding(1)), CLEAN_RT])], tmp_path=tmp_path)
    assert "debug:unit:A:r2" in labels(out) and "fix:unit:A:r2" not in labels(out)


@pytest.mark.parametrize("bad,note", [(None, "rt-null-budget"), ({"findingsCount": 2, "findings": [finding(1)]}, "rt-mismatch-budget")])
def test_untrustworthy_review_every_round_blocks_as_unknown(tmp_path: Path, bad: dict | None, note: str) -> None:
    out = run([("^rt:unit:A:", [bad])], tmp_path=tmp_path)
    assert len([l for l in labels(out) if l.startswith("rt:unit:A:")]) == 5
    assert "defer:unit:A:" + note in labels(out)
    assert out["result"]["redteamUnknownBlocked"] and out["result"]["protocolBlocked"]


def test_unknown_round_keeps_stall_memory(tmp_path: Path) -> None:
    out = run([("^rt:unit:A:", [rt(finding(1)), None, rt(finding(1)), CLEAN_RT])], tmp_path=tmp_path)
    assert "debug:unit:A:r3" in labels(out)


def test_unrecognised_severity_blocks(tmp_path: Path) -> None:
    out = run([("^rt:unit:A:", [rt(dict(finding(1), severity="High")), CLEAN_RT])], tmp_path=tmp_path)
    assert "fix:unit:A:r1" in labels(out) and logged(out, "unrecognised severity")


@pytest.mark.parametrize("gates,expect_note", [([None], "defer:unit:A:gate-null:r1"), ([RED, RED], "defer:unit:A:tests-red:r1")])
def test_gate_failure_stops_loop_and_blocks(tmp_path: Path, gates: list, expect_note: str) -> None:
    out = run([("^rt:unit:A:", [rt(finding(1))]), ("^gate:unit:", gates)], tmp_path=tmp_path)
    assert expect_note in labels(out)
    r = out["result"]
    assert r["fixLoopTestsBlocked"] and r["protocolBlocked"] and r["testsRed"]
    assert "archive" not in labels(out)


def test_red_gate_fixed_by_test_fix_continues(tmp_path: Path) -> None:
    out = run([("^rt:unit:A:", [rt(finding(1)), CLEAN_RT]), ("^gate:unit:A:r1$", [RED]), ("^gate:unit:A:r1:recheck$", [GREEN])], tmp_path=tmp_path)
    assert "fix:tests:unit:A:r1" in labels(out) and "rt:unit:A:r2" in labels(out)
    assert not out["result"]["protocolBlocked"] and out["result"]["testsRed"]


def test_wide_findings_fan_out_per_file(tmp_path: Path) -> None:
    many = rt(*[finding(n, file="src/f%d.py" % n) for n in range(7)])
    out = run([("^rt:unit:A:", [many, CLEAN_RT])], tmp_path=tmp_path)
    assert len([l for l in labels(out) if l.startswith("fix:unit:A:r1:")]) == 7


def test_groups_review_concurrently_and_overlap_serialises(tmp_path: Path) -> None:
    wv = wave([group("A", ["src/a.py"]), group("B", ["src/b.py"])])
    out = run(pf=dict(PF, scopePaths=[]), wv=wv, tmp_path=tmp_path)
    assert logged(out, "2 groups concurrently")
    wv = wave([group("A", ["src/a.py"]), group("B", ["src/a.py"])])
    out = run(pf=dict(PF, scopePaths=[]), wv=wv, tmp_path=tmp_path)
    assert logged(out, "Scope overlap detected")


def test_crashed_group_is_unknown_not_clean(tmp_path: Path) -> None:
    wv = wave([group("A", ["src/a.py"]), group("B", ["src/b.py"])])
    out = run([("^rt:unit:B:", ["__THROW__"])], pf=dict(PF, scopePaths=[]), wv=wv, tmp_path=tmp_path)
    assert out["result"]["redteamUnknownBlocked"] and out["result"]["protocolBlocked"]


def test_phase_redteam_skipped_for_one_group_and_run_for_many(tmp_path: Path) -> None:
    assert not any(l.startswith("rt:phase") for l in labels(run(tmp_path=tmp_path)))
    wv = wave([group("A", ["src/a.py"]), group("B", ["src/b.py"])])
    assert "rt:phase:r1" in labels(run(pf=dict(PF, scopePaths=[]), wv=wv, tmp_path=tmp_path))


def test_phase_budget_is_eight_rounds(tmp_path: Path) -> None:
    wv = wave([group("A", ["src/a.py"]), group("B", ["src/b.py"])])
    out = run([("^rt:phase:", [rt(finding(n)) for n in range(1, 9)])], pf=dict(PF, scopePaths=[]), wv=wv, tmp_path=tmp_path)
    r = out["result"]
    assert r["phaseRedteamRounds"] == 8 and r["exhausted"] and r["phaseBudgetBlocked"]
    assert [l for l in labels(out) if l.startswith("debug:phase")] == ["debug:phase:r%d" % n for n in range(4, 8)]
    assert "defer:phase:budget-exhausted" in labels(out)


# ─── Protocol audit ───────────────────────────────────────────────────────────


def _proto_wave(path: str) -> dict:
    return wave([group("A", [path])])


def test_protocol_legs_follow_scope(tmp_path: Path) -> None:
    ls = labels(run(pf=dict(PF, scopePaths=[]), wv=_proto_wave("src/routes/mcp.py"), tmp_path=tmp_path))
    assert "proto:mcp" in ls and "proto:seam" in ls and "proto:a2a" not in ls and "proto:a2ui" not in ls
    ls = labels(run(pf=dict(PF, scopePaths=[]), wv=_proto_wave("src/auth/oauth_tokens.py"), tmp_path=tmp_path))
    assert {"proto:a2a", "proto:mcp", "proto:agui", "proto:seam"} <= set(ls) and "proto:a2ui" not in ls
    ls = labels(run(tmp_path=tmp_path))
    assert not any(l.startswith("proto:") for l in ls)


def test_null_advisor_blocks(tmp_path: Path) -> None:
    out = run([("^proto:mcp$", [None])], pf=dict(PF, scopePaths=[]), wv=_proto_wave("src/routes/mcp.py"), tmp_path=tmp_path)
    assert out["result"]["protocolBlocked"] and "archive" not in labels(out)


def test_critical_protocol_finding_fixed_and_rechecked(tmp_path: Path) -> None:
    crit = {"criticalCount": 1, "highCount": 0, "findings": [{"protocol": "MCP", "severity": "critical", "rule": "r", "description": "d"}]}
    common = dict(pf=dict(PF, scopePaths=[]), wv=_proto_wave("src/routes/mcp.py"), tmp_path=tmp_path)
    out = run([("^proto:mcp$", [crit])], **common)
    ls = labels(out)
    assert ls.index("proto:fix") < ls.index("gate:proto:fix") < ls.index("proto:recheck:mcp")
    assert "proto:recheck:seam" in ls and not out["result"]["protocolBlocked"]
    out = run([("^proto:mcp$", [crit]), ("^proto:recheck:mcp$", [crit])], **common)
    assert out["result"]["protocolBlocked"] and "proto:defer-note" in labels(out)
    out = run([("^proto:mcp$", [crit]), ("^gate:proto:fix", [RED])], **common)
    assert out["result"]["protocolBlocked"] and not any(l.startswith("proto:recheck") for l in labels(out))


def test_seam_prompts_carry_full_scope(tmp_path: Path) -> None:
    crit = {"criticalCount": 1, "highCount": 0, "findings": [{"protocol": "MCP", "severity": "critical", "rule": "r", "description": "d"}]}
    wv = wave([group("A", ["src/auth/middleware.py", "src/tools/a.py"])])
    out = run([("^proto:mcp$", [crit])], pf=dict(PF, scopePaths=[]), wv=wv, tmp_path=tmp_path)
    for label in ["proto:seam", "proto:recheck:seam"]:
        prompt = call(out, label)["prompt"]
        assert "src/auth/middleware.py" in prompt and "src/tools/a.py" in prompt, label


# ─── Codify ───────────────────────────────────────────────────────────────────


def test_findings_without_codify_line_still_reach_codify(tmp_path: Path) -> None:
    bare = {k: v for k, v in finding(1).items() if k != "codify"}
    out = run([("^rt:unit:A:", [rt(bare), CLEAN_RT])], tmp_path=tmp_path)
    assert logged(out, "missing a Codify: line: F1")
    assert "problem 1" in call(out, "codify:LRN-007")["prompt"]


def test_budget_exit_findings_reach_codify_and_note(tmp_path: Path) -> None:
    out = run([("^rt:unit:A:", [rt(finding(n)) for n in range(1, 6)])], tmp_path=tmp_path)
    assert "problem 5" in call(out, "defer:unit:A:budget-exhausted")["prompt"]
    assert any(l.startswith("codify:LRN-007") for l in labels(out))
    wv = wave([group("A", ["src/a.py"]), group("B", ["src/b.py"])])
    out = run([("^rt:phase:", [rt(finding(n)) for n in range(1, 9)])], pf=dict(PF, scopePaths=[]), wv=wv, tmp_path=tmp_path)
    assert "problem 8" in call(out, "defer:phase:budget-exhausted")["prompt"]
    assert any(l.startswith("codify:LRN") for l in labels(out))


def test_lrn_capture_is_capped_batched_and_numbered_from_preflight(tmp_path: Path) -> None:
    wide = rt(*[finding(n, file="src/f%d.py" % (n % 3)) for n in range(23)])
    out = run([("^rt:unit:A:", [wide, CLEAN_RT])], tmp_path=tmp_path)
    ls = labels(out)
    assert "defer:codify:lrn-cap-exceeded" in ls
    assert [l for l in ls if l.startswith("codify:LRN")] == ["codify:LRN-007..LRN-011", "codify:LRN-012..LRN-016",
                                                             "codify:LRN-017..LRN-021", "codify:LRN-022..LRN-026"]
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
def test_untrustworthy_archive_gate_blocks(tmp_path: Path, intent: dict | None) -> None:
    out = run([("^gate:archive-commit$", [intent])], tmp_path=tmp_path)
    assert out["result"]["protocolBlocked"] and "archive" not in labels(out)


@pytest.mark.parametrize("field", ["offendingPaths", "offendingHarnessPaths", "offendingUndeclaredImports", "offendingUndeclaredScope"])
def test_each_offending_list_blocks_archive(tmp_path: Path, field: str) -> None:
    out = run([("^gate:archive-commit$", [dict(ARCH_OK, **{field: ["src/x.py"]})])], tmp_path=tmp_path)
    assert out["result"]["protocolBlocked"] and "archive" not in labels(out)
    assert logged(out, "src/x.py")


def test_archive_gate_receives_full_scope(tmp_path: Path) -> None:
    out = run(tmp_path=tmp_path)
    assert "python3 - '[\"src/tools/a.py\"]' <<'ARCHIVE_GATE'" in call(out, "gate:archive-commit")["prompt"]


def test_template_deliverable_absent_at_archive_blocks(tmp_path: Path) -> None:
    wv = wave([group("A", ["harness/workflows/x.js", "template/.claude/workflows/x.js"])])
    out = run([("^gate:archive-commit$", [dict(ARCH_OK, templateDirExists=False)])],
              pf=dict(PF, scopePaths=["harness/workflows/x.js"], templateDirExists=True), wv=wv, tmp_path=tmp_path)
    assert out["result"]["protocolBlocked"] and "archive" not in labels(out)
    assert logged(out, "template/ absent")


def test_missing_plan_row_self_heals_once(tmp_path: Path) -> None:
    missing = dict(ARCH_CHECK_OK, rowPresent=False, matchCount=0)
    out = run([("^gate:archive-plan-row", [missing, ARCH_CHECK_OK])], tmp_path=tmp_path)
    assert "archive-plan-row-repair" in labels(out) and not out["result"]["archivePlanRowMissing"]
    out = run([("^gate:archive-plan-row", [missing])], tmp_path=tmp_path)
    assert out["result"]["archivePlanRowMissing"]


@pytest.mark.parametrize("check", [None, dict(ARCH_CHECK_OK, archivedFileExists=False), dict(ARCH_CHECK_OK, activeFileExists=True)])
def test_unverified_archive_move_is_incomplete(tmp_path: Path, check: dict | None) -> None:
    out = run([("^gate:archive-plan-row", [check])], tmp_path=tmp_path)
    assert out["result"]["archivePlanRowMissing"] and logged(out, "INCOMPLETE")


def test_plan_row_check_requires_this_wave_file(tmp_path: Path) -> None:
    prompt = call(run(tmp_path=tmp_path), "gate:archive-plan-row")["prompt"]
    assert "grep -i 'w010' workspace/todos/plan.md | grep -ci -F 'active/w010-x.md'" in prompt
    missing = dict(ARCH_CHECK_OK, rowPresent=False, matchCount=0)
    repair = call(run([("^gate:archive-plan-row", [missing, ARCH_CHECK_OK])], tmp_path=tmp_path), "archive-plan-row-repair")["prompt"]
    assert "DIFFERENT file" in repair and "leave it untouched" in repair


def test_archive_never_overwrites_completed_records(tmp_path: Path) -> None:
    prompt = call(run(tmp_path=tmp_path), "archive")["prompt"]
    step1, step4 = prompt.split("\n2. ")[0], prompt.split("\n4. ")[1]
    assert "workspace/todos/completed/w010-x.md` already exists" in step1 and "never move or overwrite" in step1
    assert "does not already exist" in step4 and "skip that file" in step4


# ─── args and budget ──────────────────────────────────────────────────────────


def test_string_args_are_parsed(tmp_path: Path) -> None:
    out = run(args=json.dumps({"waveFile": "workspace/todos/active/w010-x.md", "today": "2026-10-20"}), tmp_path=tmp_path)
    assert out["result"]["waveId"] == "w010"


@pytest.mark.parametrize("args,msg", [({"today": "x"}, "missing required arg(s): waveFile"), ("{nope", "not valid JSON"),
                                      ({"waveFile": "w", "today": "t", "agentBudget": 0}, "agentBudget must be a positive number"),
                                      ({"waveFile": "w", "today": "t", "agentBudget": "abc"}, "agentBudget must be a positive number")])
def test_bad_args_fail_fast(tmp_path: Path, args: object, msg: str) -> None:
    out = run(args=args, tmp_path=tmp_path)
    assert msg in out["error"] and out["calls"] == []


def test_budget_scales_with_group_count_unless_overridden(tmp_path: Path) -> None:
    assert logged(run(tmp_path=tmp_path), "agent budget=150")
    wv = wave([group(g, ["src/%s.py" % g]) for g in "ABCDE"])
    assert logged(run(pf=dict(PF, scopePaths=[]), wv=wv, tmp_path=tmp_path), "agent budget=325")
    out = run(pf=dict(PF, scopePaths=[]), wv=wv, args={"waveFile": "workspace/todos/active/w010-x.md", "today": "t", "agentBudget": 900}, tmp_path=tmp_path)
    assert logged(out, "agent budget=900")


def test_budget_exceeded_stops_loudly_with_note(tmp_path: Path) -> None:
    out = run(args={"waveFile": "workspace/todos/active/w010-x.md", "today": "t", "agentBudget": 3}, tmp_path=tmp_path)
    assert "agent-call budget exceeded" in out["error"]
    assert labels(out)[-1] == "defer:agent-budget-exceeded"


# ─── mirrors ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("wf", WAVE_CYCLE_COPIES[1:], ids=[str(p.relative_to(REPO_ROOT)) for p in WAVE_CYCLE_COPIES[1:]])
def test_mirrors_behave_identically(tmp_path: Path, wf: Path) -> None:
    assert wf.read_bytes() == WC.read_bytes()


# ─── deterministic scripts, run for real ──────────────────────────────────────


def _script(name: str) -> str:
    src = WC.read_text(encoding="utf-8")
    m = re.search(r"const " + name + r" = (\[.*?\n\])\.join\('\\n'\)", src, re.S)
    assert m, name + " not found"
    return subprocess.run(["node", "-e", "process.stdout.write(" + m.group(1) + ".join('\\n'))"],
                          capture_output=True, text=True, check=True).stdout


def _git(repo: Path, *a: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, check=True).stdout


def _repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "t@t")
    _git(path, "config", "user.name", "t")
    return path


def _commit_all(repo: Path) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "c")


def _write(repo: Path, rel: str, text: str = "") -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def _py(script: str, repo: Path, *argv: str) -> dict:
    proc = subprocess.run([sys.executable, "-", *argv], input=script, capture_output=True, text=True, cwd=repo, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_preflight_script_reports_repo_facts(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "r")
    _write(repo, "src/__init__.py")
    _write(repo, "workspace/todos/active/w010-x.md", "x")
    _write(repo, "workspace/todos/active/w009-y.md", "y")
    _write(repo, "workspace/todos/active/CHECKPOINT-w009.md", "c")
    _write(repo, "workspace/todos/completed/w003-old.md", "o")
    _write(repo, "workspace/learning/LRN-004-a.md", "")
    _write(repo, "workspace/learning/README.md", "| LRN-012 | x |")
    _commit_all(repo)
    _write(repo, "src/dirty.py", "x")
    out = _py(_script("PREFLIGHT_PY"), repo, "workspace/todos/active/w010-x.md")
    assert out == {"ok": True, "error": "", "wrongRunnerForRepoLayout": False, "completedFileExists": False,
                   "templateDirExists": False, "otherActiveWaves": ["w009-y.md"], "dirtyPathCount": 1,
                   "behindCount": 0, "lrnNext": 13}
    _write(repo, "workspace/todos/completed/w010-x.md", "")
    shutil.rmtree(repo / "src")
    _write(repo, "agent_sdk/__init__.py")
    (repo / "template").mkdir()
    out = _py(_script("PREFLIGHT_PY"), repo, "workspace/todos/active/w010-x.md")
    assert out["completedFileExists"] and out["wrongRunnerForRepoLayout"] and out["templateDirExists"]


def test_preflight_script_outside_git_is_not_ok(tmp_path: Path) -> None:
    (tmp_path / "plain").mkdir()
    out = _py(_script("PREFLIGHT_PY"), tmp_path / "plain", "w010-x.md")
    assert out["ok"] is False and out["error"]


def _agent_repo(tmp_path: Path) -> Path:
    repo = _repo(tmp_path / "agent")
    _write(repo, "src/__init__.py")
    _write(repo, "src/tools/__init__.py")
    _write(repo, "src/tools/quote.py", "x = 1\n")
    _write(repo, "src/sources/__init__.py")
    _write(repo, "src/sources/pricing.py")
    _write(repo, "src/common/__init__.py")
    _write(repo, "src/config.py")
    _write(repo, "pyproject.toml", "[project]\n")
    _commit_all(repo)
    return repo


def _gate(repo: Path, scope: list[str]) -> dict:
    return _py(_script("ARCHIVE_GATE_PY"), repo, json.dumps(scope))


def test_archive_gate_clean_tree(tmp_path: Path) -> None:
    out = _gate(_agent_repo(tmp_path), ["src/tools/quote.py"])
    assert out == {"ok": True, "error": "", "dirtyPaths": [], "offendingPaths": [], "offendingHarnessPaths": [],
                   "offendingUndeclaredImports": [], "offendingUndeclaredScope": [], "templateDirExists": False}


def test_archive_gate_flags_uncommitted_scope_and_harness_files(tmp_path: Path) -> None:
    repo = _agent_repo(tmp_path)
    _write(repo, "src/tools/quote.py", "x = 2\n")
    _write(repo, "tests/test_quote.py", "")
    _write(repo, "pyproject.toml", "[project]\nname='x'\n")
    _write(repo, "docs/notes.md", "")
    out = _gate(repo, ["src/tools/quote.py"])
    assert out["offendingPaths"] == ["src/tools/quote.py"]
    assert sorted(out["offendingHarnessPaths"]) == ["docs/notes.md", "pyproject.toml", "tests/test_quote.py"]


@pytest.mark.parametrize("import_line,extracted", [
    ("from ..common.origin import guard_origin", "src/common/origin.py"),            # relative, symbol from module
    ("from ..common import origin", "src/common/origin.py"),                         # relative, submodule
    ("from ..common import newsubpkg", "src/common/newsubpkg/__init__.py"),          # relative, sub-package
    ("from src.common.origin import guard_origin", "src/common/origin.py"),          # absolute, symbol from module
    ("from src.common import origin", "src/common/origin.py"),                       # absolute, submodule
    ("import src.common.origin", "src/common/origin.py"),                            # absolute, direct
    ("from src import newtop", "src/newtop.py"),                                     # bare top-level
])
def test_archive_gate_finds_untracked_imported_modules(tmp_path: Path, import_line: str, extracted: str) -> None:
    repo = _agent_repo(tmp_path)
    _write(repo, extracted, "def guard_origin(): pass\n")
    _write(repo, "src/tools/quote.py", import_line + "\n")
    out = _gate(repo, ["src/tools/quote.py"])
    assert out["offendingUndeclaredImports"] == [extracted]
    # Declaring it clears the import finding.
    assert _gate(repo, ["src/tools/quote.py", extracted])["offendingUndeclaredImports"] == []


def test_archive_gate_ignores_tracked_missing_and_third_party_imports(tmp_path: Path) -> None:
    repo = _agent_repo(tmp_path)
    _write(repo, "src/tools/quote.py", "from ..sources import pricing\nfrom ..nothing import here\nimport agent_sdk\nfrom agent_sdk.x import y\n")
    assert _gate(repo, ["src/tools/quote.py"])["offendingUndeclaredImports"] == []


def test_archive_gate_flags_undeclared_tracked_source_by_exact_match(tmp_path: Path) -> None:
    repo = _agent_repo(tmp_path)
    _write(repo, "src/config.py", "changed = True\n")
    out = _gate(repo, ["src/tools/quote.py"])
    assert out["offendingUndeclaredScope"] == ["src/config.py"]
    assert _gate(repo, ["src/config.py"])["offendingUndeclaredScope"] == []


def test_archive_gate_sees_nested_template_repo(tmp_path: Path) -> None:
    repo = _agent_repo(tmp_path)
    _write(repo, ".gitignore", "template/\n")
    _commit_all(repo)
    tpl = _repo(repo / "template")
    _write(tpl, ".claude/workflows/wave-cycle.js", "a")
    _commit_all(tpl)
    out = _gate(repo, ["src/tools/quote.py"])
    assert out["templateDirExists"] is True
    assert any(p.startswith("template/ (unpushed or no upstream") for p in out["offendingHarnessPaths"])
    _write(tpl, ".claude/workflows/wave-cycle.js", "b")
    assert "template/.claude/workflows/wave-cycle.js" in _gate(repo, ["src/tools/quote.py"])["offendingHarnessPaths"]


def test_archive_gate_outside_git_is_not_ok(tmp_path: Path) -> None:
    (tmp_path / "plain").mkdir()
    out = _py(_script("ARCHIVE_GATE_PY"), tmp_path / "plain", "[]")
    assert out["ok"] is False and out["error"]
