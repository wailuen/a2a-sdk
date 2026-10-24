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
// args.keyFile     : path to a temp file containing the service API key (written by
//                    the skill caller using require('fs') before invoking this
//                    workflow; the workflow itself cannot use require() in the sandbox)
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
      enum: ['none', 'transport-divergence', 'code-bug', 'content-type-gap', 'persona-gap', 'upstream-issue', 'bad-scenario', 'harness-contamination', 'rate-limited'],
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
  const runKey         = (a.runId ? a.runId + '-' : '') + s.id

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
    'Base URL:    ' + a.baseUrl + '\n' +
    'Service key: read from ' + a._keyFile + ' (do NOT log or echo the value)\n\n' +

    '━━━ INSTRUCTIONS ━━━\n\n' +
    'Run this scenario on ' + (runA2A && runAGUI ? 'BOTH transports in sequence' : transports[0].toUpperCase() + ' transport only') + '.\n' +
    'Score each transport independently (rate-limited turns excluded). Both must score ≥ 7 for passed=true.\n\n' +

    // ── A2A transport ──────────────────────────────────────────────────────────
    (runA2A ? (
    '══ PART 1 — A2A transport (POST /v1/message:stream) ══════════════════════\n\n' +
    'Drive ' + maxTurns + '-turn maximum (minimum 3 turns) via the A2A streaming endpoint.\n\n' +

    'For EACH A2A turn:\n\n' +

    '1. Run the turn helper (throttled to 3 concurrent turns across all scenarios; retries\n' +
    '   429 / "too many requests" / failed task / empty reply with back-off inside a 540 s budget;\n' +
    '   task/context ids are saved only on success). Do NOT write your own httpx script:\n\n' +
    '   ACC_QUERY="QUERY_TEXT" .venv/bin/python3 -m agent_sdk.testing.turns --transport a2a \\\n' +
    '       --base-url ' + a.baseUrl + ' --key-file ' + a._keyFile + ' --run-key ' + runKey + '\n\n' +
    '   Run this Bash command with timeout 600000 (ms). The default Bash timeout (120 s) is shorter\n' +
    '   than the helper budget and would kill it before it prints. The helper always prints one JSON\n' +
    '   line before 600 s. Never score a turn from a killed or empty Bash call.\n\n' +
    '   Parse the JSON on stdout: {ok, reply, contentTypes, attempts} on success, or\n' +
    '   {ok:false, failureClass, reason, status, attempts} on failure. Never print the key.\n' +
    '   If ok=false and failureClass="rate-limited", the turn was throttled by the server\n' +
    '   even after retries: do NOT score it 1–2. Mark the turn rate-limited (leave it out of\n' +
    '   the min score) and use failureClass "rate-limited" if no scored turn failed.\n\n' +

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
    'Clean up the helper state files /tmp/acc-' + runKey + '-a2a-* (task, ctx, and state).\n\n'
    ) : '') +

    // ── AG-UI transport ────────────────────────────────────────────────────────
    (runAGUI ? (
    '══ PART ' + (runA2A ? '2' : '1') + ' — AG-UI transport (POST /ag-ui/run SSE) ════════════════════════\n\n' +
    'Drive ' + maxTurns + '-turn maximum (minimum 3 turns) via the AG-UI run endpoint.\n' +
    'Start a FRESH conversation — do not reuse A2A task state.\n\n' +

    'For EACH AG-UI turn:\n\n' +

    '1. Run the turn helper (same throttle and retry rules as A2A; the message list is\n' +
    '   restored on a failed attempt so a retry never duplicates the user message):\n\n' +
    '   ACC_QUERY="QUERY_TEXT" .venv/bin/python3 -m agent_sdk.testing.turns --transport agui \\\n' +
    '       --base-url ' + a.baseUrl + ' --key-file ' + a._keyFile + ' --run-key ' + runKey + '\n\n' +
    '   Run this Bash command with timeout 600000 (ms) (the helper prints one JSON line before 600 s;\n' +
    '   the default 120 s Bash timeout would kill it first).\n\n' +
    '   Parse: {ok, reply, toolsCalled, contentTypes, attempts}. A failure with\n' +
    '   failureClass="rate-limited" is handled exactly as for A2A (not scored 1–2).\n\n' +

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
    'Clean up the helper state file /tmp/acc-' + runKey + '-agui-msgs.json.\n\n'
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
    '  rate-limited           — turns throttled by the server (HTTP 429 / "too many requests") even after\n' +
    '                           helper retries; infrastructure, NOT an agent failure. Never score 1–2; excluded\n' +
    '                           from min scores and from self-heal fixes (re-run later with fewer slots)\n' +
    '  harness-contamination  — cross-run bleed detected; flag when ALL THREE conditions hold:\n' +
    '                           (1) tool names from a different scenario appear in this turn context,\n' +
    '                           (2) this scenario\'s min score is anomalously low vs a single-run baseline,\n' +
    '                           (3) you explicitly identify the contaminating scenario or tool set.\n' +
    '  none                   — all turns ≥ 7 on all transports\n\n' +

    'RULES:\n' +
    '- A rate-limited turn (helper failureClass "rate-limited") is never scored 1–2; omit it from min scores.\n' +
    '  If every turn on a transport was rate-limited, set the minScore of that transport to 1 (schema minimum, not a score), passed=false and failureClass "rate-limited". Untested turns are "not run", never 10/10.\n' +
    '- Never hard-fail on a network timeout — score the turn 1, rationale "timeout".\n' +
    '- If only one transport was run (--transport flag), set the other minScore to 10 and turns to [].\n' +
    '- Return structured output matching the schema exactly.\n'
  )
}

// ─── main ─────────────────────────────────────────────────────────────────────

phase('Run')

// args may arrive JSON-encoded as a string (GH-131 / GH-229); errors name fields only,
// never echo the raw args or any value (keyFile is the admin key path).
let normalizedArgs
if (typeof args === 'string') {
  try {
    normalizedArgs = JSON.parse(args)
  } catch (e) {
    throw new Error(
      'acceptance-api: args arrived as a string but is not valid JSON — pass { scenarios, baseUrl, keyFile } ' +
      '(or a JSON-encoded string of the same shape).'
    )
  }
} else {
  normalizedArgs = args || {}
}
if (normalizedArgs === null || typeof normalizedArgs !== 'object' || Array.isArray(normalizedArgs)) {
  throw new Error('acceptance-api: args is not valid JSON object — pass { scenarios, baseUrl, keyFile }.')
}
const badArgs = []
if (!Array.isArray(normalizedArgs.scenarios)) badArgs.push('scenarios (must be an array)')
if (!normalizedArgs.baseUrl) badArgs.push('baseUrl')
if (!normalizedArgs.keyFile) badArgs.push('keyFile')
if (normalizedArgs.transports != null && !Array.isArray(normalizedArgs.transports)) badArgs.push('transports (must be an array)')
if (normalizedArgs.onlyIds != null && !Array.isArray(normalizedArgs.onlyIds)) badArgs.push('onlyIds (must be an array)')
if (badArgs.length > 0) {
  throw new Error(
    'acceptance-api: missing or invalid arg(s): ' + badArgs.join(', ') +
    ' — pass { scenarios, baseUrl, keyFile } (or a JSON-encoded string of the same shape).'
  )
}
const BASE_URL = normalizedArgs.baseUrl

const transports = (normalizedArgs.transports && normalizedArgs.transports.length > 0) ? normalizedArgs.transports : ['a2a', 'agui']

const scenarios = (normalizedArgs.onlyIds && normalizedArgs.onlyIds.length > 0)
  ? normalizedArgs.scenarios.filter(function(s) { return normalizedArgs.onlyIds.indexOf(s.id) !== -1 })
  : normalizedArgs.scenarios

log('Running ' + scenarios.length + ' scenario(s) in parallel  |  transports: ' + transports.join(' + ') + '  |  ' + BASE_URL)

// ── Secret externalisation ────────────────────────────────────────────────────
// The service key is NOT passed as args.adminKey.  Instead the skill caller (which
// runs outside the workflow sandbox and has access to require('fs') / require('crypto'))
// writes the key to a per-run chmod-600 temp file and passes only the file path
// as args.keyFile.  Sub-agents read the key from disk; it never appears in the
// workflow args object or in harness transcripts.
//
// SI-2 spirit: the key must not appear in logs or agent transcripts.  The temp-
// file indirection is the closest available mechanism given the harness sandbox
// has no CommonJS require() and therefore no direct fs/crypto access.
//
// Cleanup: the caller must NOT unlink args.keyFile after Workflow() returns; it is
// reused by later re-runs and removed at the skill's 'Service key teardown'.
const _keyFile = normalizedArgs.keyFile

const enrichedArgs = Object.assign({}, normalizedArgs, { transports: transports, _keyFile: _keyFile })

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
// live path uses (FINAL SCORING / RULES: an un-run transport scores
// 10, not 1).  A crashed agent only fails the transports that were actually
// active for this run; transports not in `transports` were never exercised and
// must not drag the summary aggregate to 1.
const ranA2A  = transports.indexOf('a2a') !== -1
const ranAGUI = transports.indexOf('agui') !== -1
const results = rawResults.map(function(r, i) {
  if (r != null) {
    // Infrastructure failure class must never count as a pass (GH-210).
    return r.failureClass === 'rate-limited' ? Object.assign({}, r, { passed: false }) : r
  }
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
const rateLimited = results.filter(function(r) { return r.failureClass === 'rate-limited' }).length
const failed     = results.filter(function(r) { return !r.passed && r.failureClass !== 'rate-limited' }).length
const scored     = results.filter(function(r) { return r.failureClass !== 'rate-limited' })
const a2aMin     = scored.length > 0 ? scored.reduce(function(m, r) { return Math.min(m, r.a2aMinScore) }, 10) : 0
const aguiMin    = scored.length > 0 ? scored.reduce(function(m, r) { return Math.min(m, r.aguiMinScore) }, 10) : 0
const diverged   = results.filter(function(r) { return r.failureClass === 'transport-divergence' }).length

log(
  (results.length > 0 ? passed + '/' + results.length + ' passed' : '0/0 scenarios (empty run)') +
  '  |  A2A min: ' + a2aMin + '/10' +
  '  |  AG-UI min: ' + aguiMin + '/10' +
  (diverged ? '  |  transport-divergence: ' + diverged : '') +
  (rateLimited ? '  |  not run (rate-limited): ' + rateLimited : '') +
  '  |  failed: ' + failed
)

return results
