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
if (scenario.deleteDate) delete globalThis.Date
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


def _todo_scan_script(wf: Path) -> str:
    js = (
        "const s=require('fs').readFileSync(process.argv[1],'utf8');"
        "const m=s.match(/const TODO_SCAN_PY = (\\[[\\s\\S]*?\\]\\.join\\('\\\\n'\\))/);"
        "console.log(eval(m[1]))"
    )
    return subprocess.run(["node", "-e", js, str(wf)], capture_output=True, text=True, check=True).stdout


def facts_for(wv: dict, wf: Path, tmp_path: Path) -> list:
    """Run the runner's real todo scan over a wave file built from the scripted wave's bodies."""
    lines = ["# Wave w010", "**Depends:** (none)", ""]
    for g in wv["groups"]:
        for t in g["todos"]:
            lines.append("- [ ] `%s` %s \u2016 group:%s" % (t["id"], t["title"], g["label"]))
            lines.extend("  " + b if b.strip() else b for b in t["body"].split("\n"))
    md = tmp_path / "facts-wave.md"
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    scan = tmp_path / "todo_scan.py"
    scan.write_text(_todo_scan_script(wf), encoding="utf-8")
    proc = subprocess.run([sys.executable, str(scan), str(md)], capture_output=True, text=True, check=True)
    return json.loads(proc.stdout)


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
        args: object = None, wf: Path = WC, tmp_path: Path, no_date: bool = False) -> dict:
    wv_default = wv or wave()
    pf_final = dict(pf or PF)
    if "todoFacts" not in pf_final:
        pf_final["todoFacts"] = facts_for(wv_default, wf, tmp_path)
    defaults = [
        ("^parse:preflight", [pf_final]),
        ("^clock:", [{"now": 2000000000.0}]),
        ("^parse(:replan)?$", [wv_default]),
        ("^deliv:", [{"ok": True, "checked": [g["label"] for g in wv_default["groups"]], "missing": []}]),
        ("^scan:scope:", [{"paths": sorted(set(wv_default["allCreates"]) | set(wv_default["allModifies"]))}]),
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
        "deleteDate": no_date,
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
    assert any(p.startswith("template/ (unpushed or not on origin/main") for p in out["offendingHarnessPaths"])
    _write(tpl, ".claude/workflows/wave-cycle.js", "b")
    assert "template/.claude/workflows/wave-cycle.js" in _gate(repo, ["src/tools/quote.py"])["offendingHarnessPaths"]


def test_archive_gate_outside_git_is_not_ok(tmp_path: Path) -> None:
    (tmp_path / "plain").mkdir()
    out = _py(_script("ARCHIVE_GATE_PY"), tmp_path / "plain", "[]")
    assert out["ok"] is False and out["error"]


# ─── stale redteam findings (GH-211) ──────────────────────────────────────────

WF = WC


def quoted(n: int, quote: str = "x = 1", file: str = "src/tools/a.py") -> dict:
    return dict(finding(n, file=file), line=3, quote=quote)


def _stale_script(wf: Path) -> str:
    js = (
        "const s=require('fs').readFileSync(process.argv[1],'utf8');"
        "const m=s.match(/const STALE_CHECK_PY = (\\[[\\s\\S]*?\\]\\.join\\('\\\\n'\\))/);"
        "console.log(eval(m[1]))"
    )
    return subprocess.run(["node", "-e", js, str(wf)], capture_output=True, text=True, check=True).stdout


def test_quote_seen_present_then_gone_is_dropped_and_not_blocking(tmp_path: Path) -> None:
    out = run([("^rt:unit:A:", [rt(quoted(1)), rt(quoted(1))]),
               ("^stale:unit:A:", [{"ok": True, "stale": [], "present": [0]}, {"ok": True, "stale": [0], "present": []}])],
              wf=WF, tmp_path=tmp_path)
    ls = labels(out)
    assert "fix:unit:A:r1" in ls and "stale:unit:A:r2" in ls
    assert "fix:unit:A:r2" not in ls and "debug:unit:A:r2" not in ls
    assert logged(out, "stale finding dropped")
    assert not out["result"]["protocolBlocked"]


def test_quote_never_seen_present_stays_blocking_at_round_one(tmp_path: Path) -> None:
    out = run([("^rt:unit:A:", [rt(quoted(1)), CLEAN_RT]),
               ("^stale:unit:A:", [{"ok": True, "stale": [0], "present": []}])], wf=WF, tmp_path=tmp_path)
    assert "fix:unit:A:r1" in labels(out)
    assert logged(out, "unverifiable quote")
    assert not logged(out, "stale finding dropped")


def test_null_stale_check_keeps_every_finding(tmp_path: Path) -> None:
    out = run([("^rt:unit:A:", [rt(quoted(1), quoted(2)), CLEAN_RT]), ("^stale:unit:A:", [None])],
              wf=WF, tmp_path=tmp_path)
    assert "fix:unit:A:r1" in labels(out)
    assert logged(out, "keeping every finding")


def test_untrustworthy_stale_indices_keep_findings(tmp_path: Path) -> None:
    out = run([("^rt:unit:A:", [rt(quoted(1)), CLEAN_RT]), ("^stale:unit:A:", [{"ok": True, "stale": [7]}])],
              wf=WF, tmp_path=tmp_path)
    assert "fix:unit:A:r1" in labels(out)


def test_findings_without_quotes_skip_the_check_and_stay(tmp_path: Path) -> None:
    out = run([("^rt:unit:A:", [rt(dict(finding(1), quote=""), finding(2)), CLEAN_RT])], wf=WF, tmp_path=tmp_path)
    assert not [l for l in labels(out) if l.startswith("stale:")]
    assert "fix:unit:A:r1" in labels(out)


def test_stale_check_script_greps_fixed_strings_and_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\ny = [2]\n")
    items = [
        {"file": "a.py", "quote": "x = 1"},
        {"file": "a.py", "quote": "gone = 9"},
        {"file": "a.py", "quote": "y = [2]"},
        {"file": "a.py", "quote": ""},
        {"file": "missing.py", "quote": "x = 1"},
        {"file": "../a.py", "quote": "nope"},
    ]
    proc = subprocess.run([sys.executable, "-c", _stale_script(WF), json.dumps(items)],
                          cwd=tmp_path, capture_output=True, text=True)
    assert json.loads(proc.stdout) == {"ok": True, "stale": [1], "present": [0, 2]}


def test_rt_schema_requires_quote_and_line() -> None:
    for wf in WAVE_CYCLE_COPIES:
        text = wf.read_text()
        block = text[text.index("const RT_SCHEMA"):text.index("const PROTO_SCHEMA")]
        req = re.search(r"required: \['id'[^\]]*\]", block).group(0)
        assert "'quote'" in req and "'line'" in req, wf


# ─── deliverable gate, derived deps, scope re-scan, HUMAN GATE (GH-208) ───────

_SDK_WAVE = REPO_ROOT / ".claude" / "workflows" / "sdk-wave.js"
RUNNERS = [p for p in (WC, _SDK_WAVE) if p.exists()]
RUNNER_IDS = [p.name for p in RUNNERS]


def two_dep_groups(b_body: str = "body of B-1", deps: dict | None = None) -> dict:
    a = group("A", ["src/tools/a.py"])
    b = group("B", ["src/tools/b.py"])
    b["todos"][0]["body"] = b_body
    return wave([a, b], deps if deps is not None else {"A": [], "B": ["A"]})


def deliv_missing(label: str, *paths: str) -> dict:
    return {"ok": True, "checked": ["A", "B"], "missing": [{"label": label, "paths": list(paths)}]}


@pytest.mark.parametrize("wf", RUNNERS, ids=RUNNER_IDS)
def test_dependent_not_dispatched_when_creates_path_is_missing(tmp_path: Path, wf: Path) -> None:
    out = run([("^deliv:tier1", [deliv_missing("A", "src/tools/a.py")])], wv=two_dep_groups(), wf=wf, tmp_path=tmp_path)
    ls = labels(out)
    assert "impl:A-1" in ls
    assert "impl:B-1" not in ls
    assert "defer:incomplete:A" in ls
    assert "Write workspace/todos/deferred/w010-group-A-incomplete.md" in call(out, "defer:incomplete:A")["prompt"]
    assert not [l for l in ls if l.startswith("rt:unit:B")]
    assert "archive" not in ls
    r = out["result"]
    assert r["deliverablesBlocked"] and r["protocolBlocked"]
    assert r["failedGroups"] == ["A"] and r["prunedGroups"] == ["B"]


@pytest.mark.parametrize("wf", RUNNERS, ids=RUNNER_IDS)
@pytest.mark.parametrize("bad", [None, {"ok": False, "checked": [], "missing": []}, {"ok": True, "checked": ["A"]},
                                 {"ok": True, "checked": [], "missing": []}])
def test_null_or_malformed_deliverable_gate_counts_every_path_missing(tmp_path: Path, wf: Path, bad: object) -> None:
    out = run([("^deliv:", [bad])], wv=two_dep_groups(), wf=wf, tmp_path=tmp_path)
    assert "impl:B-1" not in labels(out)
    assert out["result"]["failedGroups"] == ["A"]
    assert "src/tools/a.py" in call(out, "defer:incomplete:A")["prompt"]
    assert logged(out, "fail closed")


@pytest.mark.parametrize("wf", RUNNERS, ids=RUNNER_IDS)
def test_depends_line_adds_dep_the_model_parse_missed(tmp_path: Path, wf: Path) -> None:
    wv = two_dep_groups("body of B-1\n  - Depends: A-1", deps={"A": [], "B": []})
    out = run([("^deliv:tier1", [deliv_missing("A", "src/tools/a.py")])], wv=wv, wf=wf, tmp_path=tmp_path)
    assert "impl:B-1" not in labels(out)
    assert out["result"]["prunedGroups"] == ["B"]


@pytest.mark.parametrize("wf", RUNNERS, ids=RUNNER_IDS)
def test_depends_line_orders_dependent_after_its_dependency(tmp_path: Path, wf: Path) -> None:
    wv = two_dep_groups("body of B-1\n  - Depends: A-1", deps={"A": [], "B": []})
    ls = labels(run(wv=wv, wf=wf, tmp_path=tmp_path))
    assert ls.index("impl:A-1") < ls.index("deliv:tier1") < ls.index("impl:B-1")


@pytest.mark.parametrize("wf", RUNNERS, ids=RUNNER_IDS)
def test_complete_groups_run_dependents_and_archive(tmp_path: Path, wf: Path) -> None:
    out = run(wv=two_dep_groups(), wf=wf, tmp_path=tmp_path)
    assert {"impl:A-1", "impl:B-1", "archive"} <= set(labels(out))
    assert not out["result"]["deliverablesBlocked"]


@pytest.mark.parametrize("wf", RUNNERS, ids=RUNNER_IDS)
def test_scope_added_mid_run_reaches_review_and_archive_gate(tmp_path: Path, wf: Path) -> None:
    out = run([("^scan:scope:unit:A:r1", [{"paths": ["src/tools/a.py", "src/tools/late.py"]}]),
               ("^scan:scope:", [{"paths": ["src/tools/a.py", "src/tools/late.py"]}])], tmp_path=tmp_path, wf=wf)
    assert "src/tools/late.py" in call(out, "rt:unit:A:r1")["prompt"]
    assert "src/tools/late.py" in call(out, "gate:archive-commit")["prompt"]


@pytest.mark.parametrize("wf", RUNNERS, ids=RUNNER_IDS)
def test_null_scope_rescan_is_unknown_not_clean(tmp_path: Path, wf: Path) -> None:
    out = run([("^scan:scope:", [None])], tmp_path=tmp_path, wf=wf)
    assert not [l for l in labels(out) if l.startswith("rt:unit:")]
    assert out["result"]["redteamUnknownBlocked"] and out["result"]["protocolBlocked"]


@pytest.mark.parametrize("wf", RUNNERS, ids=RUNNER_IDS)
def test_phase_round_rescans_scope_too(tmp_path: Path, wf: Path) -> None:
    out = run(wv=two_dep_groups(), tmp_path=tmp_path, wf=wf)
    assert "scan:scope:phase:r1" in labels(out)


@pytest.mark.parametrize("wf", RUNNERS, ids=RUNNER_IDS)
def test_status_not_done_free_text_does_not_gate(tmp_path: Path, wf: Path) -> None:
    out = run(wv=two_dep_groups("body of B-1\n  - Status: NOT DONE"), wf=wf, tmp_path=tmp_path)
    assert "impl:B-1" in labels(out)
    assert not out["result"]["deliverablesBlocked"]


HUMAN = "body of B-1\n  - HUMAN GATE: owner sign-off required"


@pytest.mark.parametrize("wf", RUNNERS, ids=RUNNER_IDS)
def test_human_gate_without_release_line_holds_group_and_prunes_dependents(tmp_path: Path, wf: Path) -> None:
    a = group("A", ["src/tools/a.py"])
    a["todos"][0]["body"] = HUMAN
    b = group("B", ["src/tools/b.py"])
    out = run(wv=wave([a, b], {"A": [], "B": ["A"]}), wf=wf, tmp_path=tmp_path)
    ls = labels(out)
    assert "impl:A-1" not in ls and "impl:B-1" not in ls
    assert "defer:held:A" in ls
    assert not [l for l in ls if l.startswith("rt:unit:")]
    assert out["result"]["deliverablesBlocked"] and "archive" not in ls


@pytest.mark.parametrize("wf", RUNNERS, ids=RUNNER_IDS)
def test_human_gate_with_release_issue_url_runs(tmp_path: Path, wf: Path) -> None:
    body = HUMAN + "\n  - Release: https://github.com/wailuen/a2a-sdk/issues/208"
    out = run(wv=two_dep_groups(body), wf=wf, tmp_path=tmp_path)
    assert "impl:B-1" in labels(out)
    assert not out["result"]["deliverablesBlocked"]


@pytest.mark.parametrize("wf", RUNNERS, ids=RUNNER_IDS)
def test_human_gate_release_line_without_issue_url_still_holds(tmp_path: Path, wf: Path) -> None:
    out = run(wv=two_dep_groups(HUMAN + "\n  - Release: approved by email"), wf=wf, tmp_path=tmp_path)
    assert "impl:B-1" not in labels(out)


def _gate_script(wf: Path) -> str:
    src = wf.read_text(encoding="utf-8")
    scan = re.search(r"const SCOPE_SCAN_PY = (\[.*?\n\])\.join\('\\n'\)", src, re.S).group(0)
    gate = (re.search(r"const PATH_RULE_PY = [^\n]*\n", src).group(0)
            + re.search(r"const DELIVERABLE_GATE_PY = PATH_RULE_PY .*?\]\.join\('\\n'\)", src, re.S).group(0))
    js = scan + "\n" + gate + "\nprocess.stdout.write(DELIVERABLE_GATE_PY)"
    return subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout


@pytest.mark.parametrize("wf", RUNNERS, ids=RUNNER_IDS)
def test_deliverable_script_checks_existence_acceptance_verdict_and_patterns(tmp_path: Path, wf: Path) -> None:
    import os
    import time

    (tmp_path / "src").mkdir()
    (tmp_path / "src/present.py").write_text("x")
    (tmp_path / "workspace/acceptance").mkdir(parents=True)
    (tmp_path / "workspace/acceptance/pass.md").write_text("# Acceptance\n\n**Verdict:** PASS\n")
    (tmp_path / "workspace/acceptance/pending.md").write_text("Verdict: PASS\nTest: [pending]\n")
    (tmp_path / "workspace/acceptance/fail.md").write_text("Verdict: FAIL\n")
    (tmp_path / "src/old_x.py").write_text("x")
    old = time.time() - 1000
    os.utime(tmp_path / "src/old_x.py", (old, old))
    (tmp_path / "src/new_y.py").write_text("y")
    groups = {
        "ok": ["src/present.py", "workspace/acceptance/pass.md", "src/new_*.py"],
        "bad": ["src/absent.py", "workspace/acceptance/pending.md", "workspace/acceptance/fail.md", "src/old_*.py", "src/none_*.py"],
    }
    spec = json.dumps({"since": time.time() - 100, "groups": groups})
    out = _py(_gate_script(wf), tmp_path, spec)
    assert out["ok"] is True and out["checked"] == ["bad", "ok"]
    assert out["missing"] == [{"label": "bad", "paths": groups["bad"]}]


# ─── review fixes: gate classification, placeholders, clock, todo scan ────────

@pytest.mark.parametrize("wf", RUNNERS, ids=RUNNER_IDS)
def test_deliverable_script_only_treats_workspace_acceptance_md_as_record(tmp_path: Path, wf: Path) -> None:
    for d in ("harness/workflows", "tests", "workspace/acceptance"):
        (tmp_path / d).mkdir(parents=True)
    (tmp_path / "harness/workflows/acceptance-api.js").write_text("x")
    (tmp_path / "tests/test_gh71_acceptance_api_stream.py").write_text("x")
    rec = tmp_path / "workspace/acceptance"
    (rec / "heading.md").write_text("# Acceptance\n\n## Verdict\n\nPASS - all green\n")
    (rec / "heading-colon.md").write_text("## Verdict: PASS\n")
    (rec / "first-fails.md").write_text("Verdict: FAIL\n\nlater rerun\nVerdict: PASS\n")
    (rec / "heading-fail-then-pass.md").write_text("## Verdict\nFAIL\n\n**Verdict:** PASS\n")
    (rec / "empty.md").write_text("no verdict here\n")
    groups = {
        "ok": ["harness/workflows/acceptance-api.js", "tests/test_gh71_acceptance_api_stream.py",
               "workspace/acceptance/heading.md", "workspace/acceptance/heading-colon.md"],
        "bad": ["workspace/acceptance/first-fails.md", "workspace/acceptance/heading-fail-then-pass.md",
                "workspace/acceptance/empty.md", "workspace/acceptance/absent.md"],
    }
    out = _py(_gate_script(wf), tmp_path, json.dumps({"since": 1.0, "groups": groups}))
    assert out["missing"] == [{"label": "bad", "paths": groups["bad"]}]


@pytest.mark.parametrize("wf", RUNNERS, ids=RUNNER_IDS)
def test_planner_placeholders_are_patterns_not_files(tmp_path: Path, wf: Path) -> None:
    import os
    import time

    scan = tmp_path / "scan.py"
    scan.write_text(_scan_script(wf), encoding="utf-8")
    wave_md = tmp_path / "w.md"
    wave_md.write_text(
        "- [ ] `G5-1` learnings\n  - Creates: (modifies `CHANGELOG.md`, new `workspace/learning/LRN-NNN-stale-redteam-findings.md`,"
        " `workspace/acceptance/run-NNN.json`)\n", encoding="utf-8")
    scanned = json.loads(subprocess.run([sys.executable, str(scan), str(wave_md)], capture_output=True, text=True,
                                        check=True).stdout)
    placeholders = [p for p in scanned if "NNN" in p]
    assert len(placeholders) == 2
    (tmp_path / "workspace/learning").mkdir(parents=True)
    (tmp_path / "workspace/learning/LRN-455-stale-redteam-findings.md").write_text("x")
    paths = placeholders
    stale_since = time.time() + 100
    out = _py(_gate_script(wf), tmp_path, json.dumps({"since": time.time() - 100, "groups": {"G5": paths}}))
    assert out["missing"] == [{"label": "G5", "paths": ["workspace/acceptance/run-NNN.json"]}]
    out = _py(_gate_script(wf), tmp_path, json.dumps({"since": stale_since, "groups": {"G5": paths}}))
    assert out["missing"] == [{"label": "G5", "paths": paths}]
    old = time.time() - 1000
    os.utime(tmp_path / "workspace/learning/LRN-455-stale-redteam-findings.md", (old, old))


@pytest.mark.parametrize("since", [None, "soon", True])
@pytest.mark.parametrize("wf", RUNNERS, ids=RUNNER_IDS)
def test_missing_or_malformed_since_counts_every_pattern_missing(tmp_path: Path, wf: Path, since: object) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/new_y.py").write_text("y")
    (tmp_path / "src/present.py").write_text("x")
    spec = json.dumps({"since": since, "groups": {"g": ["src/present.py", "src/new_*.py"]}})
    out = _py(_gate_script(wf), tmp_path, spec)
    assert out["missing"] == [{"label": "g", "paths": ["src/new_*.py"]}]


def _scan_script(wf: Path) -> str:
    src = wf.read_text(encoding="utf-8")
    scan = re.search(r"const SCOPE_SCAN_PY = (\[.*?\n\])\.join\('\\n'\)", src, re.S).group(0)
    return subprocess.run(["node", "-e", scan + "\nprocess.stdout.write(SCOPE_SCAN_PY)"],
                          capture_output=True, text=True, check=True).stdout


@pytest.mark.parametrize("wf", RUNNERS, ids=RUNNER_IDS)
def test_runner_never_reads_the_clock_in_the_sandbox(tmp_path: Path, wf: Path) -> None:
    out = run(wv=two_dep_groups(), wf=wf, tmp_path=tmp_path, no_date=True)
    assert "error" not in out, out
    assert "clock:implement-start" in labels(out) and "archive" in labels(out)
    assert '"since":2000000000' in call(out, "deliv:tier1")["prompt"]


@pytest.mark.parametrize("wf", RUNNERS, ids=RUNNER_IDS)
@pytest.mark.parametrize("bad", [None, {"now": 0}, {"now": "x"}, "done"])
def test_untrustworthy_clock_passes_null_since_to_the_gate(tmp_path: Path, wf: Path, bad: object) -> None:
    out = run([("^clock:", [bad])], wf=wf, tmp_path=tmp_path)
    assert '"since":null' in call(out, "deliv:tier1")["prompt"]
    assert logged(out, "Implement start time unavailable")


@pytest.mark.parametrize("wf", RUNNERS, ids=RUNNER_IDS)
def test_deps_and_hold_come_from_the_wave_file_not_the_model_relay(tmp_path: Path, wf: Path) -> None:
    # The model's Parse dropped both the Depends: line and the HUMAN GATE marker from the bodies.
    a = group("A", ["src/tools/a.py"])
    b = group("B", ["src/tools/b.py"])
    wv = wave([a, b], {"A": [], "B": []})
    facts = [{"id": "A-1", "dependsText": [], "held": True},
             {"id": "B-1", "dependsText": ["A-1"], "held": False}]
    out = run(wv=wv, pf=dict(PF, todoFacts=facts), wf=wf, tmp_path=tmp_path)
    ls = labels(out)
    assert "impl:A-1" not in ls and "impl:B-1" not in ls
    assert "defer:held:A" in ls
    assert out["result"]["prunedGroups"] == ["B"]


@pytest.mark.parametrize("wf", RUNNERS, ids=RUNNER_IDS)
def test_todo_found_by_scan_but_missing_from_parse_aborts(tmp_path: Path, wf: Path) -> None:
    facts = [{"id": "A-1", "dependsText": [], "held": False}, {"id": "Z-9", "dependsText": [], "held": False}]
    out = run(pf=dict(PF, todoFacts=facts), wf=wf, tmp_path=tmp_path)
    assert out["result"] == {"error": "todo-scan-mismatch", "waveId": "w010", "missed": ["Z-9"]}
    assert "impl:A-1" not in labels(out)


@pytest.mark.parametrize("wf", RUNNERS, ids=RUNNER_IDS)
@pytest.mark.parametrize("bad", [{"id": "A-1", "held": False}, {"id": "A-1", "dependsText": [1], "held": False},
                                 {"id": "A-1", "dependsText": [], "held": "yes"}])
def test_malformed_todo_facts_stop_before_parse(tmp_path: Path, wf: Path, bad: dict) -> None:
    out = run(pf=dict(PF, todoFacts=[bad]), wf=wf, tmp_path=tmp_path)
    assert out["result"]["error"] == "preflight-failed" and labels(out) == ["parse:preflight"]


def test_todo_scan_script_reads_depends_hold_and_skips_marked_todos(tmp_path: Path) -> None:
    md = tmp_path / "w.md"
    md.write_text(
        "# Wave\n**Depends:** WAVE-0\n\n## G1\n"
        "- [ ] `A-1` first\n  - Depends: (none)\n"
        "- [ ] `B-1` second ‖ group:B\n  - **Depends:** A-1, `C-2`\n  - HUMAN GATE: owner sign-off\n"
        "- [ ] `C-2` third\n  - HUMAN GATE: x\n  - Release: https://github.com/wailuen/a2a-sdk/issues/208\n"
        "- [~] `D-3` skipped\n  - HUMAN GATE: y\n"
        "\n## G2\n  - Depends: STRAY\n", encoding="utf-8")
    script = tmp_path / "todo_scan.py"
    script.write_text(_todo_scan_script(WC), encoding="utf-8")
    got = json.loads(subprocess.run([sys.executable, str(script), str(md)], capture_output=True, text=True,
                                    check=True).stdout)
    assert got == [
        {"id": "A-1", "dependsText": ["(none)"], "held": False},
        {"id": "B-1", "dependsText": ["A-1, `C-2`"], "held": True},
        {"id": "C-2", "dependsText": [], "held": False},
    ]


# ─── SDK candidate re-check + opt-in auto-filing (GH-223) ─────────────────────

SDK_WAVE_JS = REPO_ROOT / ".claude" / "workflows" / "sdk-wave.js"
SECRET_QUOTE = "API_KEY = 'sk-live1234567890abcdef'"


def cand(n: int, file: str, quote: str = "x = 1", description: str | None = None,
         component: str = "harness/workflow") -> dict:
    return {"id": "F%d" % n, "quote": quote, "description": description or "problem %d" % n,
            "severity": "high", "component": component, "rationale": "r", "file": file}


def candidate_run(run_fn, tmp_path: Path, cands: list[dict], *, seen_present: bool = True,
                  recheck: object = None, filed: object = "unset", auto: bool | None = None,
                  file_default: bool = True) -> dict:
    findings = [dict(finding(int(c["id"][1:]), file=c["file"]), line=3, quote=c["quote"],
                     description=c["description"]) for c in cands]
    present = list(range(len(cands))) if seen_present else []
    rules = [
        ("^rt:unit:A:", [rt(*findings), CLEAN_RT]),
        ("^stale:unit:A:", [{"ok": True, "stale": [], "present": present}]),
        ("^sdk:scan$", [{"sdkCandidates": cands}]),
        ("^sdk:recheck$", [recheck if recheck is not None else {"ok": True, "stale": [], "present": []}]),
    ]
    if filed != "unset":
        rules.append(("^sdk:file$", [filed]))
    args = {"waveFile": "workspace/todos/active/w010-x.md", "today": "2026-10-20"}
    if auto is not None:
        args["autoFileSdkIssues"] = auto
    return run_fn(rules, args=args, tmp_path=tmp_path)


def candidates_prompt(out: dict) -> str:
    return call(out, "sdk:candidates")["prompt"]


def check_default_files_nothing(run_fn, file: str, tmp_path: Path) -> None:
    out = candidate_run(run_fn, tmp_path, [cand(1, file)])
    assert "sdk:file" not in labels(out)
    assert "Status: still-open" in candidates_prompt(out)
    assert "nothing is filed automatically" in candidates_prompt(out)


def check_fixed_in_wave_needs_prior_presence(run_fn, file: str, tmp_path: Path) -> None:
    gone = {"ok": True, "stale": [0], "present": []}
    (tmp_path / "a").mkdir()
    out = candidate_run(run_fn, tmp_path / "a", [cand(1, file)], recheck=gone)
    assert "Status: fixed-in-wave" in candidates_prompt(out)
    (tmp_path / "b").mkdir()
    out = candidate_run(run_fn, tmp_path / "b", [cand(1, file)], recheck=gone, seen_present=False)
    assert "Status: still-open" in candidates_prompt(out)


def check_fail_closed_statuses(run_fn, file: str, tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    out = candidate_run(run_fn, tmp_path / "a", [cand(1, file, quote="")])
    assert "sdk:recheck" not in labels(out) and "Status: still-open" in candidates_prompt(out)
    (tmp_path / "b").mkdir()
    out = candidate_run(run_fn, tmp_path / "b", [cand(1, file)], recheck={"ok": False, "stale": [0]})
    assert "Status: still-open" in candidates_prompt(out) and logged(out, "no trustworthy result")
    (tmp_path / "c").mkdir()
    out = candidate_run(run_fn, tmp_path / "c", [cand(1, file)], recheck={"ok": True, "stale": [5]})
    assert "Status: still-open" in candidates_prompt(out)


def check_recheck_reuses_stale_script(run_fn, file: str, tmp_path: Path) -> None:
    out = candidate_run(run_fn, tmp_path, [cand(1, file)])
    p = call(out, "sdk:recheck")["prompt"]
    assert "import json, os, subprocess, sys" in p and "grep" in p


def check_auto_files_only_still_open(run_fn, file: str, tmp_path: Path) -> None:
    cands = [cand(1, file, description="fixed one"), cand(2, file, description="open one")]
    out = candidate_run(
        run_fn, tmp_path, cands, auto=True,
        recheck={"ok": True, "stale": [0], "present": [1]},
        filed={"ok": True, "ghAvailable": True,
               "results": [{"index": 1, "status": "filed", "url": "https://github.com/wailuen/a2a-sdk/issues/901"}]})
    p = call(out, "sdk:file")["prompt"]
    assert "open one" in p and "fixed one" not in p
    cp = candidates_prompt(out)
    assert "Status: fixed-in-wave" in cp and "https://github.com/wailuen/a2a-sdk/issues/901" in cp
    assert "-R" in p and "--body-file" in p and "wailuen/a2a-sdk" in p


def check_auto_with_nothing_open_does_not_call_gh(run_fn, file: str, tmp_path: Path) -> None:
    out = candidate_run(run_fn, tmp_path, [cand(1, file)], auto=True,
                        recheck={"ok": True, "stale": [0], "present": []})
    assert "sdk:file" not in labels(out)


@pytest.mark.parametrize("filed", [None, {"ok": True, "ghAvailable": False, "results": []}, {"ok": False, "ghAvailable": False, "results": []}])
def check_auto_falls_back_to_file(run_fn, file: str, tmp_path: Path, filed: object) -> None:
    out = candidate_run(run_fn, tmp_path, [cand(1, file)], auto=True, filed=filed)
    assert "error" not in out, out.get("error")
    assert "sdk:candidates" in labels(out) and "archive" in labels(out)
    assert logged(out, "stay in workspace/sdk-candidates.md")


def check_quote_never_leaves_the_runner(run_fn, file: str, tmp_path: Path) -> None:
    out = candidate_run(run_fn, tmp_path, [cand(1, file, quote=SECRET_QUOTE, description="hard-coded key in config")],
                        auto=True, filed={"ok": True, "ghAvailable": True, "results": []})
    for label in ("sdk:file", "sdk:candidates"):
        assert "sk-live1234567890abcdef" not in call(out, label)["prompt"], label


def check_flag_default_false_and_string_true(run_fn, file: str, tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    out = candidate_run(run_fn, tmp_path / "a", [cand(1, file)], auto="false")
    assert "sdk:file" not in labels(out)
    (tmp_path / "b").mkdir()
    out = candidate_run(run_fn, tmp_path / "b", [cand(1, file)], auto="true",
                        filed={"ok": True, "ghAvailable": True, "results": []})
    assert "sdk:file" in labels(out)


def check_classifier_keeps_id_and_quote(run_fn, file: str, tmp_path: Path) -> None:
    out = candidate_run(run_fn, tmp_path, [cand(1, file)])
    p = call(out, "sdk:scan")["prompt"]
    assert "UNCHANGED" in p and "template-mirror hygiene" in p


def _wc_run(rules, *, args, tmp_path):
    return run(rules, args=args, tmp_path=tmp_path)


def test_candidate_with_reused_finding_id_is_matched_by_quote(tmp_path: Path) -> None:
    file = "src/tools/a.py"
    fixed, still_open = cand(1, file, quote="old = 1"), cand(1, file, quote="new = 2")
    findings = [dict(finding(1, file=file), line=3, quote=c["quote"], description=c["description"] + str(i))
                for i, c in enumerate((fixed, still_open))]
    rules = [
        ("^rt:unit:A:", [rt(*findings), CLEAN_RT]),
        ("^stale:unit:A:", [{"ok": True, "stale": [], "present": [0, 1]}]),
        ("^sdk:scan$", [{"sdkCandidates": [still_open]}]),
        ("^sdk:recheck$", [{"ok": True, "stale": [], "present": [0]}]),
    ]
    out = run(rules, args={"waveFile": "workspace/todos/active/w010-x.md", "today": "2026-10-20"}, tmp_path=tmp_path)
    p = call(out, "sdk:recheck")["prompt"]
    assert "new = 2" in p and "old = 1" not in p
    assert "Status: still-open" in candidates_prompt(out)


def test_candidate_with_no_exact_original_skips_recheck(tmp_path: Path) -> None:
    out = candidate_run(_wc_run, tmp_path, [cand(1, "src/tools/a.py")], recheck={"ok": True, "stale": [0], "present": []})
    assert "Status: fixed-in-wave" in candidates_prompt(out)
    ghost = dict(cand(1, "src/tools/a.py"), quote="never reviewed")
    rules = [
        ("^rt:unit:A:", [rt(dict(finding(1, file="src/tools/a.py"), line=3, quote="x = 1", description="d")), CLEAN_RT]),
        ("^stale:unit:A:", [{"ok": True, "stale": [], "present": [0]}]),
        ("^sdk:scan$", [{"sdkCandidates": [ghost]}]),
    ]
    (tmp_path / "b").mkdir()
    out = run(rules, args={"waveFile": "workspace/todos/active/w010-x.md", "today": "2026-10-20"}, tmp_path=tmp_path / "b")
    assert "sdk:recheck" not in labels(out) and "Status: still-open" in candidates_prompt(out)


def test_default_files_nothing(tmp_path: Path) -> None:
    check_default_files_nothing(_wc_run, "src/tools/a.py", tmp_path)


def test_fixed_in_wave_needs_prior_presence(tmp_path: Path) -> None:
    check_fixed_in_wave_needs_prior_presence(_wc_run, "src/tools/a.py", tmp_path)


def test_candidate_status_fails_closed(tmp_path: Path) -> None:
    check_fail_closed_statuses(_wc_run, "src/tools/a.py", tmp_path)


def test_recheck_reuses_stale_script(tmp_path: Path) -> None:
    check_recheck_reuses_stale_script(_wc_run, "src/tools/a.py", tmp_path)


def test_auto_files_only_still_open(tmp_path: Path) -> None:
    check_auto_files_only_still_open(_wc_run, "src/tools/a.py", tmp_path)


def test_auto_with_nothing_open_does_not_call_gh(tmp_path: Path) -> None:
    check_auto_with_nothing_open_does_not_call_gh(_wc_run, "src/tools/a.py", tmp_path)


@pytest.mark.parametrize("filed", [None, {"ok": True, "ghAvailable": False, "results": []}, {"ok": False, "ghAvailable": False, "results": []}])
def test_auto_falls_back_to_file(tmp_path: Path, filed: object) -> None:
    check_auto_falls_back_to_file(_wc_run, "src/tools/a.py", tmp_path, filed)


def test_quote_never_leaves_the_runner(tmp_path: Path) -> None:
    check_quote_never_leaves_the_runner(_wc_run, "src/tools/a.py", tmp_path)


def test_flag_default_false_and_string_true(tmp_path: Path) -> None:
    check_flag_default_false_and_string_true(_wc_run, "src/tools/a.py", tmp_path)


def test_classifier_keeps_id_and_quote(tmp_path: Path) -> None:
    check_classifier_keeps_id_and_quote(_wc_run, "src/tools/a.py", tmp_path)


# The filing script, run for real against a fake `gh` on PATH.

FAKE_GH = """#!/usr/bin/env python3
import json, os, sys
argv = sys.argv[1:]
log = os.environ["GH_LOG"]
rec = {"argv": argv}
if "--body-file" in argv:
    rec["bodyfile"] = argv[argv.index("--body-file") + 1]
    rec["body"] = open(rec["bodyfile"]).read()
open(log, "a").write(json.dumps(rec) + "\\n")
if argv[:2] == ["issue", "list"]:
    if os.environ.get("GH_LIST_FAIL"):
        sys.exit(1)
    print(os.environ.get("GH_LIST", "[]"))
elif argv[:2] == ["issue", "create"]:
    if "--label" in argv and os.environ.get("GH_NO_LABELS"):
        sys.exit(1)
    n = sum(1 for _ in open(log))
    print("https://github.com/wailuen/a2a-sdk/issues/%d" % (900 + n))
"""


def _file_script(wf: Path) -> str:
    js = (
        "const s=require('fs').readFileSync(process.argv[1],'utf8');"
        "const m=s.match(/const FILE_SDK_ISSUES_PY = (\\[[\\s\\S]*?\\]\\.join\\('\\\\n'\\))/);"
        "console.log(eval(m[1]))"
    )
    return subprocess.run(["node", "-e", js, str(wf)], capture_output=True, text=True, check=True).stdout


def run_filer(tmp_path: Path, cands: list[dict], *, wf: Path = WC, gh: bool = True, env_extra: dict | None = None):
    import os
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    if gh:
        g = bindir / "gh"
        g.write_text(FAKE_GH)
        g.chmod(0o755)
    log = tmp_path / "gh.log"
    env = {"PATH": str(bindir), "GH_LOG": str(log), **(env_extra or {})}
    if gh:
        env["PATH"] = str(bindir) + os.pathsep + os.environ["PATH"]
    payload = {"waveId": "w010", "candidates": [dict(c, index=i) for i, c in enumerate(cands)]}
    proc = subprocess.run([sys.executable, "-c", _file_script(wf), json.dumps(payload)],
                          cwd=tmp_path, capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stderr
    calls = [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []
    return json.loads(proc.stdout), calls


def fcand(desc: str, **kw) -> dict:
    return dict({"description": desc, "component": "harness/workflow", "severity": "high", "file": "harness/workflows/x.js"}, **kw)


FILER_WFS = [WC, SDK_WAVE_JS]


@pytest.mark.parametrize("wf", FILER_WFS)
def test_filer_passes_R_and_body_file_and_labels(tmp_path: Path, wf: Path) -> None:
    res, calls = run_filer(tmp_path, [fcand("missing guard")], wf=wf)
    assert res["results"][0]["status"] == "filed" and res["results"][0]["url"].startswith("https://github.com/wailuen/a2a-sdk/issues/")
    assert [c["argv"][:2] for c in calls] == [["issue", "list"], ["label", "create"], ["label", "create"], ["issue", "create"]]
    for c in calls:
        assert c["argv"][c["argv"].index("-R") + 1] == "wailuen/a2a-sdk"
    assert [c["argv"][2] for c in calls[1:3]] == ["auto-filed", "harness/workflow"]
    calls = [calls[0], calls[3], calls[3]]
    create = calls[1]["argv"]
    assert "--body-file" in create and "--body" not in create
    assert create.count("--label") == 2 and "auto-filed" in create and "harness/workflow" in create
    assert not Path(calls[1]["bodyfile"]).exists()
    assert "missing guard" in calls[1]["body"] and "harness/workflows/x.js" in calls[1]["body"]


@pytest.mark.parametrize("wf", FILER_WFS)
def test_filer_caps_at_ten(tmp_path: Path, wf: Path) -> None:
    res, calls = run_filer(tmp_path, [fcand("distinct problem number %d" % i) for i in range(13)], wf=wf)
    statuses = [r["status"] for r in res["results"]]
    assert statuses.count("filed") == 10 and statuses.count("capped") == 3
    assert sum(1 for c in calls if c["argv"][:2] == ["issue", "create"]) == 10


@pytest.mark.parametrize("wf", FILER_WFS)
def test_filer_dedupes_against_open_issues(tmp_path: Path, wf: Path) -> None:
    listing = json.dumps([{"number": 5, "title": "Missing Guard", "url": "https://github.com/wailuen/a2a-sdk/issues/5"}])
    res, calls = run_filer(tmp_path, [fcand("missing guard")], wf=wf, env_extra={"GH_LIST": listing})
    assert res["results"][0] == {"index": 0, "status": "duplicate", "url": "https://github.com/wailuen/a2a-sdk/issues/5"}
    assert not [c for c in calls if c["argv"][:2] == ["issue", "create"]]


@pytest.mark.parametrize("wf", FILER_WFS)
def test_filer_without_gh_reports_unavailable(tmp_path: Path, wf: Path) -> None:
    res, calls = run_filer(tmp_path, [fcand("missing guard")], wf=wf, gh=False)
    assert res["ok"] is True and res["ghAvailable"] is False and res["results"] == [] and calls == []


@pytest.mark.parametrize("wf", FILER_WFS)
def test_filer_unauthenticated_list_failure_falls_back(tmp_path: Path, wf: Path) -> None:
    res, calls = run_filer(tmp_path, [fcand("a"), fcand("b")], wf=wf, env_extra={"GH_LIST_FAIL": "1"})
    assert res["ghAvailable"] is False
    assert not [c for c in calls if c["argv"][:2] == ["issue", "create"]]


@pytest.mark.parametrize("wf", FILER_WFS)
@pytest.mark.parametrize("secret", ["sk-live1234567890abcdef", "ak_9f8e7d6c5b4a3210", "sk-ab", "Bearer eyJhbGciOiJIUzI1NiJ9.abc.def",
                                    "a" * 8 + "0123456789abcdef0123456789abcdef",
                                    "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "AIzaSyA1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q",
                                    "Basic dXNlcjpwYXNzd29yZA==", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
                                    "glpat-abcdEFGH1234", "pk_live_abcd1234", "password=Hunter2Secret!", "xoxb-123"])
def test_filer_never_puts_secrets_in_gh_argv_or_body(tmp_path: Path, wf: Path, secret: str) -> None:
    res, calls = run_filer(tmp_path, [fcand("hard-coded %s in config" % secret, file="src/%s.py" % secret)], wf=wf)
    blob = json.dumps(calls)
    assert secret not in blob
    for needle in ("sk-", "ak_"):
        assert needle not in blob
    assert res["results"][0]["status"] in ("filed", "skipped-secret")


@pytest.mark.parametrize("wf", FILER_WFS)
def test_filer_files_without_labels_when_labels_are_refused(tmp_path: Path, wf: Path) -> None:
    res, calls = run_filer(tmp_path, [fcand("missing guard")], wf=wf, env_extra={"GH_NO_LABELS": "1"})
    assert res["results"][0]["status"] == "filed"
    creates = [c["argv"] for c in calls if c["argv"][:2] == ["issue", "create"]]
    assert len(creates) == 2 and "--label" in creates[0] and "--label" not in creates[1]


@pytest.mark.parametrize("wf", FILER_WFS)
def test_filer_search_text_is_the_redacted_title(tmp_path: Path, wf: Path) -> None:
    res, calls = run_filer(tmp_path, [fcand("key sk-live1234567890abcdef leaks")], wf=wf)
    search = calls[0]["argv"][calls[0]["argv"].index("--search") + 1]
    assert "sk-" not in search and "[REDACTED]" in search


@pytest.mark.parametrize("wf", FILER_WFS)
def test_filer_leaves_unredactable_candidate_unsearched_and_unfiled(tmp_path: Path, wf: Path) -> None:
    res, calls = run_filer(tmp_path, [fcand("keys look like sk- followed by text")], wf=wf)
    assert res["results"] == [{"index": 0, "status": "skipped-secret"}]
    assert calls == []


# ─── cross-runner parity (sdk-wave.js is outside the byte-identical guard) ────


def _fn(text: str, name: str) -> str:
    start = text.index(name)
    return text[start:text.index("\n}\n", start) + 3]


def test_candidate_logic_matches_across_runners() -> None:
    a, b = WC.read_text(), SDK_WAVE_JS.read_text()
    for name in ("const FILE_SDK_ISSUES_PY", "const STALE_CHECK_PY", "const FILE_SCHEMA", "async function runStaleScript",
                 "async function candidateStatuses", "async function fileStillOpenCandidates", "function originalFinding",
                 "async function dropStaleFindings", "const AUTO_FILE_SDK_ISSUES"):
        assert _fn(a, name).split("\n}\n")[0] == _fn(b, name).split("\n}\n")[0], name
    for text in (a, b):
        block = text[text.index("const SDK_SCAN_SCHEMA"):text.index("const GATE_SCHEMA")]
        req = re.search(r"required: \['id'[^\]]*\]", block).group(0)
        assert "'quote'" in req and "id:" in block and "quote:" in block
        assert "wailuen/a2a-sdk" in text and "autoFileSdkIssues" in text.split("normalizedArgs")[0]
