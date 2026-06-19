export const meta = {
  name: 'acceptance-api',
  description: 'Parallel acceptance runner: fan-out 30+ scenario conversations over BOTH A2A (message/stream) and AG-UI (POST /ag-ui/run SSE) transports, judge-score each turn 1–10 per transport, classify failures, return structured dual-path results',
  phases: [
    { title: 'Run', detail: 'One agent per scenario: drive 3–5 turn conversation on A2A + AG-UI transports, judge-score per transport' },
  ],
}

// ─── args ─────────────────────────────────────────────────────────────────────
// args.scenarios   : array of {id, name, category, seedQuery, expectedTools,
//                    expectedContentTypes, maxTurns, followUpTurns?}
// args.baseUrl     : e.g. "http://localhost:8000"
// args.adminKey    : admin API key from workspace/adr/ADR-000-<env>-credentials.md
// args.agentContext: {name, description, tools: [{name, emits, description}]}
// args.onlyIds     : optional string[] — re-run only these scenario IDs
// args.transports  : optional string[] — ["a2a","agui"] (default: both)
// (followUpTurns is a PER-SCENARIO field — see s.followUpTurns above; there is
//  no top-level args.followUpTurns and one passed here would be ignored.)

// ─── schema ───────────────────────────────────────────────────────────────────

const TURN_SCHEMA = {
  type: 'object',
  required: ['turnNum', 'query', 'reply', 'contentTypesEmitted', 'score', 'rationale'],
  additionalProperties: false,
  properties: {
    turnNum:             { type: 'integer' },
    query:               { type: 'string' },
    reply:               { type: 'string' },
    toolsCalled:         { type: 'array', items: { type: 'string' } },
    contentTypesEmitted: { type: 'array', items: { type: 'string' } },
    score:               { type: 'integer', minimum: 1, maximum: 10 },
    rationale:           { type: 'string' },
    continueReason:      { type: 'string' },
  },
}

const SCENARIO_RESULT_SCHEMA = {
  type: 'object',
  required: ['scenarioId', 'name', 'passed', 'a2aMinScore', 'aguiMinScore', 'a2aTurns', 'aguiTurns', 'failureClass'],
  additionalProperties: false,
  properties: {
    scenarioId:   { type: 'string' },
    name:         { type: 'string' },
    passed:       { type: 'boolean' },
    a2aMinScore:  { type: 'integer', minimum: 1, maximum: 10 },
    aguiMinScore: { type: 'integer', minimum: 1, maximum: 10 },
    a2aTurns:     { type: 'array', items: TURN_SCHEMA },
    aguiTurns:    { type: 'array', items: TURN_SCHEMA },
    failureClass: {
      type: 'string',
      enum: ['none', 'transport-divergence', 'code-bug', 'content-type-gap', 'persona-gap', 'upstream-issue', 'bad-scenario', 'harness-contamination'],
    },
    failureDetail: { type: 'string' },
  },
}

// ─── scenario prompt builder ───────────────────────────────────────────────────

function buildScenarioPrompt(s, a) {
  const expectedTools  = (s.expectedTools || []).join(', ') || '(any — infer from query)'
  const expectedCtypes = (s.expectedContentTypes || []).join(', ') || '(any — infer from query)'
  const maxTurns       = s.maxTurns || 5
  const toolCatalog    = (a.agentContext.tools || [])
    .map(function(t) { return '  • ' + t.name + (t.emits ? ' → emits ' + t.emits : '') + (t.description ? '  (' + t.description + ')' : '') })
    .join('\n') || '  (read from src/tools/)'
  const transports     = (a.transports && a.transports.length > 0) ? a.transports : ['a2a', 'agui']
  const runA2A         = transports.indexOf('a2a') !== -1
  const runAGUI        = transports.indexOf('agui') !== -1
  const runKey         = s.id + '-' + require('crypto').randomUUID()

  return (
    'You are running an acceptance test for the agent "' + a.agentContext.name + '".\n\n' +
    'Agent description: ' + a.agentContext.description + '\n\n' +
    'Available tools:\n' + toolCatalog + '\n\n' +

    '━━━ SCENARIO ━━━\n' +
    'ID:              ' + s.id + '\n' +
    'Name:            ' + s.name + '\n' +
    'Category:        ' + (s.category || 'general') + '\n' +
    'Seed query:      ' + s.seedQuery + '\n' +
    'Expected tools:  ' + expectedTools + '\n' +
    'Expected types:  ' + expectedCtypes + '\n' +
    'Max turns:       ' + maxTurns + ' (minimum 3)\n' +
    'Transports:      ' + transports.join(' + ') + '\n\n' +

    (Array.isArray(s.followUpTurns) && s.followUpTurns.length > 0
      ? ('━━━ DETERMINISTIC FOLLOW-UPS ━━━\n' +
         'Use the queries below in order as the ACC_QUERY for turn 2, 3, … (pinned by test author).\n' +
         'Do not auto-generate follow-ups when a pinned entry exists for that turn slot.\n' +
         s.followUpTurns.map(function(q, i) { return '  Turn ' + (i + 2) + ': ' + q }).join('\n') + '\n\n')
      : '') +

    '━━━ SERVER ━━━\n' +
    'Base URL:   ' + a.baseUrl + '\n' +
    'Admin key:  ' + a.adminKey + '\n\n' +

    '━━━ INSTRUCTIONS ━━━\n\n' +
    'Run this scenario on ' + (runA2A && runAGUI ? 'BOTH transports in sequence' : transports[0].toUpperCase() + ' transport only') + '.\n' +
    'Score each transport independently. Both must score ≥ 7 for passed=true.\n\n' +

    // ── A2A transport ──────────────────────────────────────────────────────────
    (runA2A ? (
    '══ PART 1 — A2A transport (POST /v1/message:stream) ══════════════════════\n\n' +
    'Drive ' + maxTurns + '-turn maximum (minimum 3 turns) via the A2A streaming endpoint.\n\n' +

    'For EACH A2A turn:\n\n' +

    '1. Write and run this Python script (substitute ACC_QUERY env var with the actual query):\n\n' +
    '   Write to /tmp/acc-' + runKey + '-a2a-turn.py:\n' +
    '   ─────────────────────────────────────────────\n' +
    '   import asyncio, httpx, json, os\n' +
    '   from pathlib import Path\n\n' +
    '   BASE_URL = "' + a.baseUrl + '"\n' +
    '   TOKEN    = "' + a.adminKey + '"\n' +
    '   RUN_KEY  = "' + runKey + '"\n' +
    '   QUERY    = os.environ["ACC_QUERY"]\n' +
    '   TASKID_F = Path(f"/tmp/acc-{RUN_KEY}-a2a-task.txt")\n\n' +
    '   async def main():\n' +
    '       headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}\n' +
    '       task_id = TASKID_F.read_text().strip() if TASKID_F.exists() else None\n' +
    '       import uuid as _uuid\n' +
    '       msg = {"role": "user", "messageId": _uuid.uuid4().hex, "parts": [{"kind": "text", "text": QUERY}]}\n' +
    '       if task_id:\n' +
    '           msg["taskId"] = task_id\n' +
    '       body = {"message": msg}\n' +
    '       reply_parts, ctypes = [], []\n' +
    '       async with httpx.AsyncClient(base_url=BASE_URL, headers=headers, timeout=180) as c:\n' +
    '           async with c.stream("POST", "/v1/message:stream", json=body) as r:\n' +
    '               r.raise_for_status()\n' +
    '               async for line in r.aiter_lines():\n' +
    '                   if not line.startswith("data:"): continue\n' +
    '                   ev = json.loads(line[5:].strip())\n' +
    '                   if ev.get("kind") == "task":\n' +
    '                       if not task_id: task_id = ev.get("id","")\n' +
    '                   elif ev.get("kind") == "status-update":\n' +
    '                       if not task_id: task_id = ev.get("taskId","")\n' +
    '                       if ev.get("final") or (ev.get("status",{}).get("state") == "completed"):\n' +
    '                           reply_parts = [p["text"] for p in (ev.get("status",{}).get("message") or {}).get("parts",[]) if p.get("kind") == "text"]\n' +
    '                   elif ev.get("kind") == "artifact-update":\n' +
    '                       art = ev.get("artifact") or {}\n' +
    '                       art_name = art.get("name")\n' +
    '                       art_meta = art.get("metadata") or {}\n' +
    '                       art_dtype = art_meta.get("data_type") or art_name\n' +
    '                       for part in art.get("parts",[]):\n' +
    '                           if part.get("kind") == "data":\n' +
    '                               meta = part.get("metadata") or {}\n' +
    '                               ctype = art_dtype or meta.get("data_type") or meta.get("mimeType")\n' +
    '                               if ctype and ctype not in ctypes: ctypes.append(ctype)\n' +
    '       if task_id: TASKID_F.write_text(task_id)\n' +
    '       print(json.dumps({"reply": "\\n".join(reply_parts), "contentTypes": ctypes}))\n\n' +
    '   asyncio.run(main())\n' +
    '   ─────────────────────────────────────────────\n\n' +

    '   Run it:   ACC_QUERY="QUERY_TEXT" .venv/bin/python3 /tmp/acc-' + runKey + '-a2a-turn.py\n' +
    '   Parse:    {reply, contentTypes}\n\n' +

    '   Note: tool names are not observable on the A2A stream (the protocol surfaces\n' +
    '   text/data artifacts, not tool call events). Infer tool usage from the reply\n' +
    '   content and the matched content types.\n\n' +

    '2. Score the A2A reply 1–10 (content coherency):\n' +
    '   9–10 Correct content type emitted + reply directly addresses the query\n' +
    '    7–8 Minor gap (slightly verbose or marginally off-topic but on-domain)\n' +
    '    5–6 Answered something but missed the core ask or wrong content type\n' +
    '    3–4 Responded but answer does not match the query domain\n' +
    '    1–2 task status "failed", timeout, no reply, or completely wrong\n\n' +

    '3. Decide continue/stop: always continue if turn < 3; continue if turn < ' + maxTurns + ' and\n' +
    '   prior reply opens a natural follow-up; stop at natural conclusion or turn ' + maxTurns + '.\n\n' +

    '4. Follow-up query: if a pinned follow-up exists for this turn slot (see DETERMINISTIC FOLLOW-UPS\n' +
    '   above), use it verbatim. Otherwise, generate a follow-up that references specific values\n' +
    '   from the prior A2A reply (not generic).\n\n' +

    'After all A2A turns: compute a2aMinScore = min of all turn scores.\n' +
    'Clean up /tmp/acc-' + runKey + '-a2a-* files.\n\n'
    ) : '') +

    // ── AG-UI transport ────────────────────────────────────────────────────────
    (runAGUI ? (
    '══ PART ' + (runA2A ? '2' : '1') + ' — AG-UI transport (POST /ag-ui/run SSE) ════════════════════════\n\n' +
    'Drive ' + maxTurns + '-turn maximum (minimum 3 turns) via the AG-UI run endpoint.\n' +
    'Start a FRESH conversation — do not reuse A2A task state.\n\n' +

    'For EACH AG-UI turn:\n\n' +

    '1. Write and run this Python script:\n\n' +
    '   Write to /tmp/acc-' + runKey + '-agui-turn.py:\n' +
    '   ─────────────────────────────────────────────\n' +
    '   import asyncio, httpx, json, os\n' +
    '   from pathlib import Path\n' +
    '   from agent_sdk.testing import ChatDriver\n\n' +
    '   BASE_URL  = "' + a.baseUrl + '"\n' +
    '   TOKEN     = "' + a.adminKey + '"\n' +
    '   THREAD_ID = "' + runKey + '-agui"\n' +
    '   MSGS_FILE = Path("/tmp/acc-' + runKey + '-agui-msgs.json")\n' +
    '   QUERY     = os.environ["ACC_QUERY"]\n\n' +
    '   async def main():\n' +
    '       msgs = json.loads(MSGS_FILE.read_text()) if MSGS_FILE.exists() else []\n' +
    '       tools, ctypes = [], []\n' +
    '       async with httpx.AsyncClient(\n' +
    '           base_url=BASE_URL,\n' +
    '           headers={"Authorization": f"Bearer {TOKEN}"},\n' +
    '           timeout=180\n' +
    '       ) as client:\n' +
    '           driver = ChatDriver(client)\n' +
    '           reply  = await driver.agui_turn(\n' +
    '               QUERY, THREAD_ID, msgs,\n' +
    '               emit={\n' +
    '                   "tool_start": lambda n: tools.append(n),\n' +
    '                   "artifact":   lambda dt, t: ctypes.append(dt),\n' +
    '               }\n' +
    '           )\n' +
    '       MSGS_FILE.write_text(json.dumps(msgs))\n' +
    '       print(json.dumps({"reply": reply, "toolsCalled": tools, "contentTypes": ctypes}))\n\n' +
    '   asyncio.run(main())\n' +
    '   ─────────────────────────────────────────────\n\n' +

    '   Run it:   ACC_QUERY="QUERY_TEXT" .venv/bin/python3 /tmp/acc-' + runKey + '-agui-turn.py\n' +
    '   Parse:    {reply, toolsCalled, contentTypes}\n\n' +

    '2. Score the AG-UI reply 1–10 (content coherency):\n' +
    '   9–10 Correct tool called + correct content type + reply directly addresses query\n' +
    '    7–8 Minor gap (slightly verbose, marginally off-topic but on-domain)\n' +
    '    5–6 Answered something but wrong tool or missed the core ask\n' +
    '    3–4 Responded but answer does not match the query domain\n' +
    '    1–2 Error, timeout, no reply, or completely wrong\n\n' +

    '3. Decide continue/stop: same rules as A2A.\n\n' +

    '4. Follow-up query: if a pinned follow-up exists for this turn slot (see DETERMINISTIC FOLLOW-UPS\n' +
    '   above), use it verbatim. Otherwise, generate a follow-up that references specific values\n' +
    '   from the prior AG-UI reply (not generic).\n\n' +

    'After all AG-UI turns: compute aguiMinScore = min of all turn scores.\n' +
    'Clean up /tmp/acc-' + runKey + '-agui-* files.\n\n'
    ) : '') +

    // ── scoring and classification ─────────────────────────────────────────────
    '══ FINAL SCORING ════════════════════════════════════════════════════════════\n\n' +
    'passed = ' + (runA2A && runAGUI ? 'a2aMinScore ≥ 7 AND aguiMinScore ≥ 7' : 'min score ≥ 7') + '\n\n' +

    'Classify failure (if passed == false):\n' +
    '  transport-divergence   — one transport ≥ 7, the other < 7 (domain OK, wire format diverges)\n' +
    '  code-bug               — both transports < 7 due to wrong tool logic, wrong output, or error\n' +
    '  content-type-gap       — agent did not emit the expected A2UI content type on either transport\n' +
    '  persona-gap            — agent lacks the capability entirely (needs a new wave)\n' +
    '  upstream-issue         — failure due to source adapter / credential problem on both transports\n' +
    '  bad-scenario           — seed query is malformed or unanswerable by design\n' +
    '  harness-contamination  — cross-run bleed detected; flag when ALL THREE conditions hold:\n' +
    '                           (1) tool names from a different scenario appear in this turn context,\n' +
    '                           (2) this scenario\'s min score is anomalously low vs a single-run baseline,\n' +
    '                           (3) you explicitly identify the contaminating scenario or tool set.\n' +
    '  none                   — all turns ≥ 7 on all transports\n\n' +

    'IMPORTANT RULES:\n' +
    '- Never hard-fail on a network timeout — score the turn 1, rationale "timeout".\n' +
    '- If only one transport was run (--transport flag), set the other minScore to 10 and turns to [].\n' +
    '- Return structured output matching the schema exactly.\n'
  )
}

// ─── main ─────────────────────────────────────────────────────────────────────

phase('Run')

const transports = (args.transports && args.transports.length > 0) ? args.transports : ['a2a', 'agui']

const scenarios = (args.onlyIds && args.onlyIds.length > 0)
  ? args.scenarios.filter(function(s) { return args.onlyIds.indexOf(s.id) !== -1 })
  : args.scenarios

log('Running ' + scenarios.length + ' scenario(s) in parallel  |  transports: ' + transports.join(' + ') + '  |  ' + args.baseUrl)

const enrichedArgs = Object.assign({}, args, { transports: transports })

const rawResults = await pipeline(
  scenarios,
  function(s) {
    return agent(
      buildScenarioPrompt(s, enrichedArgs),
      { label: 'scenario:' + s.id, phase: 'Run', schema: SCENARIO_RESULT_SCHEMA }
    )
  }
)

// Failure reification must honor the same per-transport N/A scoring rule the
// live path uses (FINAL SCORING / IMPORTANT RULES: an un-run transport scores
// 10, not 1).  A crashed agent only fails the transports that were actually
// active for this run; transports not in `transports` were never exercised and
// must not drag the summary aggregate to 1.
const ranA2A  = transports.indexOf('a2a') !== -1
const ranAGUI = transports.indexOf('agui') !== -1
const results = rawResults.map(function(r, i) {
  if (r != null) return r
  const s = scenarios[i]
  return {
    scenarioId:    s.id,
    name:          s.name,
    passed:        false,
    a2aMinScore:   ranA2A ? 1 : 10,
    aguiMinScore:  ranAGUI ? 1 : 10,
    a2aTurns:      [],
    aguiTurns:     [],
    failureClass:  'code-bug',
    failureDetail: 'agent returned null (crash or timeout)',
  }
})

if (results.length !== scenarios.length) {
  throw new Error('acceptance-api: results.length (' + results.length + ') !== scenarios.length (' + scenarios.length + ') — pipeline dropped results must be reified as failures')
}

const passed     = results.filter(function(r) { return r.passed }).length
const failed     = results.filter(function(r) { return !r.passed }).length
const a2aMin     = results.length > 0 ? results.reduce(function(m, r) { return Math.min(m, r.a2aMinScore) }, 10) : 0
const aguiMin    = results.length > 0 ? results.reduce(function(m, r) { return Math.min(m, r.aguiMinScore) }, 10) : 0
const diverged   = results.filter(function(r) { return r.failureClass === 'transport-divergence' }).length

log(
  (results.length > 0 ? passed + '/' + results.length + ' passed' : '0/0 scenarios (empty run)') +
  '  |  A2A min: ' + a2aMin + '/10' +
  '  |  AG-UI min: ' + aguiMin + '/10' +
  (diverged ? '  |  transport-divergence: ' + diverged : '') +
  '  |  failed: ' + failed
)

return results
