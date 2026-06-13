export const meta = {
  name: 'acceptance-api',
  description: 'Parallel acceptance runner: fan-out 30+ scenario conversations over AG-UI, judge-score each turn 1–10 for content coherency, classify failures, return structured results',
  phases: [
    { title: 'Run', detail: 'One agent per scenario: drive 3–5 turn AG-UI conversation + judge-score each turn' },
  ],
}

// ─── args ─────────────────────────────────────────────────────────────────────
// args.scenarios   : array of {id, name, category, seedQuery, expectedTools,
//                    expectedContentTypes, maxTurns}
// args.baseUrl     : e.g. "http://localhost:8000"
// args.adminKey    : admin API key from workspace/adr/ADR-000-<env>-credentials.md
// args.agentContext: {name, description, tools: [{name, emits, description}]}
// args.onlyIds     : optional string[] — re-run only these scenario IDs

// ─── schema ───────────────────────────────────────────────────────────────────

const SCENARIO_RESULT_SCHEMA = {
  type: 'object',
  required: ['scenarioId', 'name', 'passed', 'minScore', 'turns', 'failureClass'],
  additionalProperties: false,
  properties: {
    scenarioId:   { type: 'string' },
    name:         { type: 'string' },
    passed:       { type: 'boolean' },
    minScore:     { type: 'integer', minimum: 1, maximum: 10 },
    turns: {
      type: 'array',
      items: {
        type: 'object',
        required: ['turnNum', 'query', 'reply', 'toolsCalled', 'contentTypesEmitted', 'score', 'rationale'],
        additionalProperties: false,
        properties: {
          turnNum:              { type: 'integer' },
          query:                { type: 'string' },
          reply:                { type: 'string' },
          toolsCalled:          { type: 'array', items: { type: 'string' } },
          contentTypesEmitted:  { type: 'array', items: { type: 'string' } },
          score:                { type: 'integer', minimum: 1, maximum: 10 },
          rationale:            { type: 'string' },
          continueReason:       { type: 'string' },
        },
      },
    },
    failureClass: {
      type: 'string',
      enum: ['none', 'code-bug', 'content-type-gap', 'persona-gap', 'upstream-issue', 'bad-scenario'],
    },
    failureDetail: { type: 'string' },
  },
}

// ─── scenario prompt builder ───────────────────────────────────────────────────

function buildScenarioPrompt(s, a) {
  const expectedTools    = (s.expectedTools || []).join(', ') || '(any — infer from query)'
  const expectedCtypes   = (s.expectedContentTypes || []).join(', ') || '(any — infer from query)'
  const maxTurns         = s.maxTurns || 5
  const toolCatalog      = (a.agentContext.tools || [])
    .map(function(t) { return '  • ' + t.name + (t.emits ? ' → emits ' + t.emits : '') + (t.description ? '  (' + t.description + ')' : '') })
    .join('\n') || '  (read from src/tools/)'

  return (
    'You are running an acceptance test for the agent "' + a.agentContext.name + '".\n\n' +

    'Agent description: ' + a.agentContext.description + '\n\n' +

    'Available tools:\n' + toolCatalog + '\n\n' +

    '━━━ SCENARIO ━━━\n' +
    'ID:                   ' + s.id + '\n' +
    'Name:                 ' + s.name + '\n' +
    'Category:             ' + (s.category || 'general') + '\n' +
    'Seed query:           ' + s.seedQuery + '\n' +
    'Expected tools:       ' + expectedTools + '\n' +
    'Expected types:       ' + expectedCtypes + '\n' +
    'Max turns:            ' + maxTurns + ' (minimum 3)\n\n' +

    '━━━ SERVER ━━━\n' +
    'Base URL:   ' + a.baseUrl + '\n' +
    'Admin key:  ' + a.adminKey + '\n\n' +

    '━━━ INSTRUCTIONS ━━━\n\n' +

    'Drive a ' + maxTurns + '-turn maximum conversation (minimum 3 turns) against\n' +
    'the agent. Use the ChatDriver over AG-UI to run each turn, then judge-score it.\n\n' +

    'For EACH turn:\n\n' +

    '1. Run the turn by writing and executing this Python script (substitute placeholders):\n\n' +

    '   Write to /tmp/acc-' + s.id + '-turn.py:\n' +
    '   ─────────────────────────────────────\n' +
    '   import asyncio, httpx, json, os\n' +
    '   from pathlib import Path\n' +
    '   from agent_sdk.testing import ChatDriver\n\n' +
    '   BASE_URL  = "' + a.baseUrl + '"\n' +
    '   TOKEN     = "' + a.adminKey + '"\n' +
    '   THREAD_ID = "' + s.id + '"\n' +
    '   MSGS_FILE = Path("/tmp/acc-' + s.id + '-msgs.json")\n' +
    '   QUERY     = os.environ["ACC_QUERY"]\n\n' +
    '   async def main():\n' +
    '       msgs  = json.loads(MSGS_FILE.read_text()) if MSGS_FILE.exists() else []\n' +
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
    '   ─────────────────────────────────────\n\n' +

    '   Then run it (substitute QUERY_TEXT with the actual query):\n' +
    '   ACC_QUERY="QUERY_TEXT" .venv/bin/python3 /tmp/acc-' + s.id + '-turn.py\n\n' +

    '   Parse the JSON output: {reply, tools, contentTypes}\n\n' +

    '2. Score the reply 1–10 (content coherency):\n' +
    '   9–10 Correct tool called + correct content type + reply directly addresses query\n' +
    '    7–8 Minor gap (slightly verbose, marginally off-topic but on-domain)\n' +
    '    5–6 Answered something but wrong tool or missed the core ask\n' +
    '    3–4 Responded but answer does not match the query domain\n' +
    '    1–2 Error, timeout, no reply, or completely wrong\n\n' +

    '3. Decide whether to continue (after scoring):\n' +
    '   - ALWAYS continue if turn < 3 (minimum 3 turns required)\n' +
    '   - CONTINUE if turn < ' + maxTurns + ' AND any of:\n' +
    '       • prior reply opened a new thread (partial answer, invites follow-up)\n' +
    '       • a tool result warrants a verification follow-up\n' +
    '       • an A2UI artifact was emitted and should be referenced\n' +
    '   - STOP if natural conclusion reached OR turn count hits ' + maxTurns + '\n\n' +

    '4. Generate the follow-up query (if continuing):\n' +
    '   - Read the prior reply and reference specific values, entity names,\n' +
    '     or recommendations from it (NOT a generic follow-up).\n' +
    '   - The follow-up must be the kind of question the same domain\n' +
    '     professional would naturally ask next.\n\n' +

    'After all turns, classify the failure (if any turn scored < 7):\n' +
    '   code-bug        — tool logic returned wrong data, wrong format, or errored\n' +
    '   content-type-gap — agent did not emit the expected A2UI content type\n' +
    '   persona-gap     — agent lacks the capability entirely (needs new wave)\n' +
    '   upstream-issue  — reply failed due to a source adapter / credential problem\n' +
    '   bad-scenario    — the seed query is malformed or unanswerable by design\n' +
    '   none            — all turns ≥ 7, no failure\n\n' +

    'IMPORTANT RULES:\n' +
    '- Never hard-fail on a network timeout — catch it, score the turn 1,\n' +
    '  rationale "timeout", and classify as code-bug or upstream-issue.\n' +
    '- Clean up /tmp/acc-' + s.id + '-* files after the last turn.\n' +
    '- Return structured output matching the schema exactly.\n'
  )
}

// ─── main ─────────────────────────────────────────────────────────────────────

phase('Run')

const scenarios = (args.onlyIds && args.onlyIds.length > 0)
  ? args.scenarios.filter(function(s) { return args.onlyIds.indexOf(s.id) !== -1 })
  : args.scenarios

log('Running ' + scenarios.length + ' scenario(s) in parallel against ' + args.baseUrl)

const results = (await pipeline(
  scenarios,
  function(s) {
    return agent(
      buildScenarioPrompt(s, args),
      { label: 'scenario:' + s.id, phase: 'Run', schema: SCENARIO_RESULT_SCHEMA }
    )
  }
)).filter(Boolean)

const passed  = results.filter(function(r) { return r.passed }).length
const failed  = results.filter(function(r) { return !r.passed }).length
const minScore = results.reduce(function(m, r) { return Math.min(m, r.minScore) }, 10)

log(passed + '/' + results.length + ' passed  |  min score: ' + minScore + '/10  |  failed: ' + failed)

return results
