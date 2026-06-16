export const meta = {
  name: 'acceptance-api',
  description: 'Parallel acceptance runner: fan-out 30+ scenario conversations over BOTH A2A (message/stream) and AG-UI (POST /run SSE) transports, judge-score each turn 1–10 per transport, classify failures, return structured dual-path results',
  phases: [
    { title: 'Run', detail: 'One agent per scenario: drive 3–5 turn conversation on A2A + AG-UI transports, judge-score per transport' },
  ],
}

// ─── args ─────────────────────────────────────────────────────────────────────
// args.scenarios   : array of {id, name, category, seedQuery, expectedTools,
//                    expectedContentTypes, maxTurns}
// args.baseUrl     : e.g. "http://localhost:8000"
// args.adminKey    : admin API key from workspace/adr/ADR-000-<env>-credentials.md
// args.agentContext: {name, description, tools: [{name, emits, description}]}
// args.onlyIds     : optional string[] — re-run only these scenario IDs
// args.transports  : optional string[] — ["a2a","agui"] (default: both)

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
      enum: ['none', 'transport-divergence', 'code-bug', 'content-type-gap', 'persona-gap', 'upstream-issue', 'bad-scenario'],
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
  const transports     = a.transports || ['a2a', 'agui']
  const runA2A         = transports.indexOf('a2a') !== -1
  const runAGUI        = transports.indexOf('agui') !== -1

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

    '━━━ SERVER ━━━\n' +
    'Base URL:   ' + a.baseUrl + '\n' +
    'Admin key:  ' + a.adminKey + '\n\n' +

    '━━━ INSTRUCTIONS ━━━\n\n' +
    'Run this scenario on ' + (runA2A && runAGUI ? 'BOTH transports in sequence' : transports[0].toUpperCase() + ' transport only') + '.\n' +
    'Score each transport independently. Both must score ≥ 7 for passed=true.\n\n' +

    // ── A2A transport ──────────────────────────────────────────────────────────
    (runA2A ? (
    '══ PART 1 — A2A transport (POST /v1/message/stream) ══════════════════════\n\n' +
    'Drive ' + maxTurns + '-turn maximum (minimum 3 turns) via the A2A JSON-RPC streaming endpoint.\n\n' +

    'For EACH A2A turn:\n\n' +

    '1. Write and run this Python script (substitute ACC_QUERY env var with the actual query):\n\n' +
    '   Write to /tmp/acc-' + s.id + '-a2a-turn.py:\n' +
    '   ─────────────────────────────────────────────\n' +
    '   import asyncio, httpx, json, os\n' +
    '   from pathlib import Path\n\n' +
    '   BASE_URL = "' + a.baseUrl + '"\n' +
    '   TOKEN    = "' + a.adminKey + '"\n' +
    '   SID      = "' + s.id + '"\n' +
    '   QUERY    = os.environ["ACC_QUERY"]\n' +
    '   TASKID_F = Path(f"/tmp/acc-{SID}-a2a-task.txt")\n\n' +
    '   async def main():\n' +
    '       headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}\n' +
    '       task_id = TASKID_F.read_text().strip() if TASKID_F.exists() else None\n' +
    '       params  = {"message": {"role": "user", "parts": [{"kind": "text", "text": QUERY}]}}\n' +
    '       if task_id:\n' +
    '           params["taskId"] = task_id\n' +
    '       reply_parts, tools, ctypes = [], [], []\n' +
    '       async with httpx.AsyncClient(base_url=BASE_URL, headers=headers, timeout=180) as c:\n' +
    '           async with c.stream("POST", "/v1/message/stream", json={\n' +
    '               "jsonrpc": "2.0", "method": "message/stream",\n' +
    '               "id": f"{SID}-a2a", "params": params\n' +
    '           }) as r:\n' +
    '               r.raise_for_status()\n' +
    '               async for line in r.aiter_lines():\n' +
    '                   if not line.startswith("data:"): continue\n' +
    '                   ev = json.loads(line[5:].strip())\n' +
    '                   method, p = ev.get("method",""), ev.get("params",{})\n' +
    '                   if method == "taskStatusUpdated":\n' +
    '                       if not task_id: task_id = p.get("id","")\n' +
    '                       for part in (p.get("message") or {}).get("parts",[]):\n' +
    '                           if part.get("kind") == "text": reply_parts.append(part["text"])\n' +
    '                   elif method == "taskArtifactUpdated":\n' +
    '                       for part in (p.get("artifact") or {}).get("parts",[]):\n' +
    '                           if part.get("kind") == "data" and part.get("mimeType"):\n' +
    '                               ctypes.append(part["mimeType"])\n' +
    '       if task_id: TASKID_F.write_text(task_id)\n' +
    '       print(json.dumps({"reply": "\\n".join(reply_parts), "tools": tools, "contentTypes": ctypes}))\n\n' +
    '   asyncio.run(main())\n' +
    '   ─────────────────────────────────────────────\n\n' +

    '   Run it:   ACC_QUERY="QUERY_TEXT" .venv/bin/python3 /tmp/acc-' + s.id + '-a2a-turn.py\n' +
    '   Parse:    {reply, tools, contentTypes}\n\n' +

    '   Note: tool names are not directly observable on the A2A stream (the protocol\n' +
    '   surfaces text/data artifacts, not tool call events). Infer tool usage from\n' +
    '   the reply content and the matched content types.\n\n' +

    '2. Score the A2A reply 1–10 (content coherency):\n' +
    '   9–10 Correct content type emitted + reply directly addresses the query\n' +
    '    7–8 Minor gap (slightly verbose or marginally off-topic but on-domain)\n' +
    '    5–6 Answered something but missed the core ask or wrong content type\n' +
    '    3–4 Responded but answer does not match the query domain\n' +
    '    1–2 task status "failed", timeout, no reply, or completely wrong\n\n' +

    '3. Decide continue/stop: always continue if turn < 3; continue if turn < ' + maxTurns + ' and\n' +
    '   prior reply opens a natural follow-up; stop at natural conclusion or turn ' + maxTurns + '.\n\n' +

    '4. Generate follow-up: reference specific values from the prior A2A reply (not generic).\n\n' +

    'After all A2A turns: compute a2aMinScore = min of all turn scores.\n' +
    'Clean up /tmp/acc-' + s.id + '-a2a-* files.\n\n'
    ) : '') +

    // ── AG-UI transport ────────────────────────────────────────────────────────
    (runAGUI ? (
    '══ PART ' + (runA2A ? '2' : '1') + ' — AG-UI transport (POST /run SSE) ════════════════════════════\n\n' +
    'Drive ' + maxTurns + '-turn maximum (minimum 3 turns) via the AG-UI run endpoint.\n' +
    'Start a FRESH conversation — do not reuse A2A task state.\n\n' +

    'For EACH AG-UI turn:\n\n' +

    '1. Write and run this Python script:\n\n' +
    '   Write to /tmp/acc-' + s.id + '-agui-turn.py:\n' +
    '   ─────────────────────────────────────────────\n' +
    '   import asyncio, httpx, json, os\n' +
    '   from pathlib import Path\n' +
    '   from agent_sdk.testing import ChatDriver\n\n' +
    '   BASE_URL  = "' + a.baseUrl + '"\n' +
    '   TOKEN     = "' + a.adminKey + '"\n' +
    '   THREAD_ID = "' + s.id + '-agui"\n' +
    '   MSGS_FILE = Path("/tmp/acc-' + s.id + '-agui-msgs.json")\n' +
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
    '       print(json.dumps({"reply": reply, "tools": tools, "contentTypes": ctypes}))\n\n' +
    '   asyncio.run(main())\n' +
    '   ─────────────────────────────────────────────\n\n' +

    '   Run it:   ACC_QUERY="QUERY_TEXT" .venv/bin/python3 /tmp/acc-' + s.id + '-agui-turn.py\n' +
    '   Parse:    {reply, tools, contentTypes}\n\n' +

    '2. Score the AG-UI reply 1–10 (content coherency):\n' +
    '   9–10 Correct tool called + correct content type + reply directly addresses query\n' +
    '    7–8 Minor gap (slightly verbose, marginally off-topic but on-domain)\n' +
    '    5–6 Answered something but wrong tool or missed the core ask\n' +
    '    3–4 Responded but answer does not match the query domain\n' +
    '    1–2 Error, timeout, no reply, or completely wrong\n\n' +

    '3. Decide continue/stop: same rules as A2A.\n\n' +

    '4. Generate follow-up: reference specific values from the prior AG-UI reply.\n\n' +

    'After all AG-UI turns: compute aguiMinScore = min of all turn scores.\n' +
    'Clean up /tmp/acc-' + s.id + '-agui-* files.\n\n'
    ) : '') +

    // ── scoring and classification ─────────────────────────────────────────────
    '══ FINAL SCORING ════════════════════════════════════════════════════════════\n\n' +
    'passed = ' + (runA2A && runAGUI ? 'a2aMinScore ≥ 7 AND aguiMinScore ≥ 7' : 'min score ≥ 7') + '\n\n' +

    'Classify failure (if passed == false):\n' +
    '  transport-divergence — one transport ≥ 7, the other < 7 (domain OK, wire format diverges)\n' +
    '  code-bug             — both transports < 7 due to wrong tool logic, wrong output, or error\n' +
    '  content-type-gap     — agent did not emit the expected A2UI content type on either transport\n' +
    '  persona-gap          — agent lacks the capability entirely (needs a new wave)\n' +
    '  upstream-issue       — failure due to source adapter / credential problem on both transports\n' +
    '  bad-scenario         — seed query is malformed or unanswerable by design\n' +
    '  none                 — all turns ≥ 7 on all transports\n\n' +

    'IMPORTANT RULES:\n' +
    '- Never hard-fail on a network timeout — score the turn 1, rationale "timeout".\n' +
    '- If only one transport was run (--transport flag), set the other minScore to 10 and turns to [].\n' +
    '- Return structured output matching the schema exactly.\n'
  )
}

// ─── main ─────────────────────────────────────────────────────────────────────

phase('Run')

const transports = args.transports || ['a2a', 'agui']

const scenarios = (args.onlyIds && args.onlyIds.length > 0)
  ? args.scenarios.filter(function(s) { return args.onlyIds.indexOf(s.id) !== -1 })
  : args.scenarios

log('Running ' + scenarios.length + ' scenario(s) in parallel  |  transports: ' + transports.join(' + ') + '  |  ' + args.baseUrl)

const enrichedArgs = Object.assign({}, args, { transports: transports })

const results = (await pipeline(
  scenarios,
  function(s) {
    return agent(
      buildScenarioPrompt(s, enrichedArgs),
      { label: 'scenario:' + s.id, phase: 'Run', schema: SCENARIO_RESULT_SCHEMA }
    )
  }
)).filter(Boolean)

const passed     = results.filter(function(r) { return r.passed }).length
const failed     = results.filter(function(r) { return !r.passed }).length
const a2aMin     = results.reduce(function(m, r) { return Math.min(m, r.a2aMinScore) }, 10)
const aguiMin    = results.reduce(function(m, r) { return Math.min(m, r.aguiMinScore) }, 10)
const diverged   = results.filter(function(r) { return r.failureClass === 'transport-divergence' }).length

log(
  passed + '/' + results.length + ' passed' +
  '  |  A2A min: ' + a2aMin + '/10' +
  '  |  AG-UI min: ' + aguiMin + '/10' +
  (diverged ? '  |  transport-divergence: ' + diverged : '') +
  '  |  failed: ' + failed
)

return results
