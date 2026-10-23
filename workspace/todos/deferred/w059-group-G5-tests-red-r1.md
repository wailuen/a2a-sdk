# w059 — group G5 — tests RED (round 1)

- Wave: w059
- Scope: unit:G5
- Date: 2026-10-22
- Round: 1
- Reason: test suite RED after the fix attempt; blocking findings below unresolved.

## Next action

Fix failing tests and remaining findings, then re-run /wave w059

SHARED WORKING TREE RULE: other agents have uncommitted work in this tree. NEVER run
`git stash`, `git reset`, `git checkout -- <path>`, `git restore`, `git clean` or
`git checkout .`. Edit files in place. Use `git show` / `git diff` to inspect old content.

## Unresolved blocking findings

### RT-001 (high) — harness/workflows/wave-cycle.js
- Description: DELIVERABLE_GATE_PY (line 472; same at .claude/workflows/sdk-wave.js:479) treats any Creates: path whose file name contains 'acceptance' as an acceptance record. Existing files then fail the gate. Running the extracted script reported harness/workflows/acceptance-api.js and tests/test_gh71_acceptance_api_stream.py as missing, which marks the group INCOMPLETE and prunes its dependents. The verdict regex also rejects a valid '## Verdict' heading followed by 'PASS' (confirmed). It accepts any 'Verdict: PASS' line anywhere in the file instead of the first verdict, which the GH-208 spec requires.
- Fix: Match the issue prototype: is_record(p) = p.startswith('workspace/acceptance/') and p.endswith('.md'). Read the FIRST verdict, in heading form ('^#+ Verdict' then the next non-blank token) or line form ('Verdict: X'), and require it to be PASS. Add script tests covering a non-record file named *acceptance*, the heading-form PASS, and a record whose first verdict is FAIL with a later PASS.
- Codify: A deliverable gate that classifies files by a substring of the file name fails closed on legitimate files; key record checks to the record directory, never to a word in the name.
- SDK candidate: yes

### RT-002 (high) — harness/workflows/wave-cycle.js
- Description: Placeholder Creates: paths are treated as concrete. The GH-208 spec names these as pattern paths ('run-NNN.json'); the same form covers LRN-NNN and C-NNN. The gate's pat() (line ~470) only recognises '*' and '?'. The Parse prompt already strips globs out of creates, so the pattern branch is dead code in practice. The extracted script reports this wave's own 'workspace/learning/LRN-NNN-stale-redteam-findings.md' as missing (the real file is LRN-455-stale-redteam-findings.md). G5 would be marked incomplete and archive blocked.
- Fix: In DELIVERABLE_GATE_PY, treat any path segment containing an NNN placeholder (regex '(?<![A-Za-z])N{3,}(?![A-Za-z])') as a pattern. Turn it into a glob ('[0-9]*') and apply the freshness rule; never check it as a concrete path. Add a test that feeds a real 'Creates: (modifies ..., new `workspace/learning/LRN-NNN-x.md`)' line through Parse and then through the gate script.
- Codify: Planner placeholders (LRN-NNN, C-NNN, run-NNN) are patterns, not files; a deliverable gate must glob them or it blocks every wave that creates a learning.
- SDK candidate: yes

### RT-003 (high) — harness/workflows/wave-cycle.js
- Description: implementStartSec (line 1143; .claude/workflows/sdk-wave.js:1138) is 'typeof Date !== "undefined" ? Math.floor(Date.now()/1000) : 0'. The file's own header (line 18) says the sandbox bans Date. If Date is undefined, since=0 and any old file matches a pattern path, so the freshness check passes when it should not. If Date exists but Date.now throws, every wave crashes at Implement. The tests run under plain node, where Date works, so neither case is exercised.
- Fix: Get the Implement start time from a deterministic script. Either run `python3 -c 'import time;print(time.time())'` through callAgent with a numeric schema, or have the gate touch a marker file at Implement start and compare mtimes inside the script. A null or malformed timestamp must count every pattern path as missing. Add a test that runs the runner with Date deleted from the global scope.
- Codify: Workflow scripts cannot read the clock (Date is banned); any time-based gate must take its timestamp from a deterministic shell step and fail closed when it is absent.
- SDK candidate: yes

### RT-004 (high) — harness/workflows/wave-cycle.js
- Description: The stale filter (dropStaleFindings line 1291, STALE_CHECK_PY line 1264, same in sdk-wave.js) also drops findings whose quote was NEVER in the file, and it does so from round 1, before any fix has run. Verified: quotes with an elided '...' or a Read-tool line-number prefix ('1143\tconst ...') both came back stale:[0,1] and would be dropped. redteam.md also gives no rule for findings about missing code or missing files. A model that invents a quote for those has a real critical/high finding silently dismissed, which is fail-open for blocking findings.
- Fix: Drop a finding only when its quote was confirmed present in an earlier round (keep a signature-to-quote-verified map in redteamFixLoop) and the file changed since. Skip the check at round 1. A quote never seen in the file keeps the finding and is logged as 'unverifiable quote'. In harness/agents/core/redteam.md, say to use quote "" for findings about absent code or files. Add a test that an unverifiable round-1 quote stays blocking.
- Codify: A 'quote no longer present' filter must only drop quotes it previously saw present; otherwise misquoted or invented quotes become a silent bypass of blocking findings.
- SDK candidate: yes

### RT-005 (high) — template/.claude/workflows/wave-cycle.js
- Description: The GH-208 template mirror was never delivered to wailuen/a2a-agent-template main. Commit 53a62d7 sits only on origin/feat/gh210-acceptance-turn-helper, and no PR is open. `git -C template diff --stat origin/main -- .claude/workflows/wave-cycle.js` shows 305 changed lines, so the LRN-335 Check fails (severity high). origin/main's planner.md and wave SKILL.md contain no 'HUMAN GATE' text. test_gh164_template_mirror_is_committed_and_pushed passes only because the local template checkout tracks the feature branch as @{upstream}.
- Fix: Open and merge a template PR so origin/main carries 53a62d7 (and the GH-209/210 commits on that branch). Harden test_gh164_template_mirror_is_committed_and_pushed to compare against origin/main, not @{upstream}.
- Codify: 'Pushed' means reachable from the template's origin/main; a mirror test keyed to @{upstream} passes on any feature branch and hides undelivered mirrors.
- SDK candidate: yes

### RT-006 (high) — harness/workflows/wave-cycle.js
- Description: deriveGroupDeps (line 525) and groupIsHeld (line ~517) read t.body from the model's Parse output, not from the wave file. The GH-208 root cause ('groupDeps comes only from the model's parse with no cross-check') is therefore unchanged. If Parse summarises or truncates a todo body, its Depends: line or HUMAN GATE marker disappears with no warning. The dependent then runs and the held group is dispatched (fail open). This breaks the AC that deps are 'derived deterministically'.
- Fix: Extend the deterministic preflight script (PREFLIGHT_PY or SCOPE_SCAN_PY's sibling) to read the wave file and emit, per todo id, its Depends: ids and its HUMAN GATE / Release status. Union these deps and the hold state from that script output. Abort Parse if a script-found todo id is missing from the model's groups.
- Codify: A 'deterministic cross-check' that re-reads model-relayed text is not deterministic; gate inputs must come from a script reading the source file.
- SDK candidate: yes
