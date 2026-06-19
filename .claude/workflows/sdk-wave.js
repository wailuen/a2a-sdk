export const meta = {
  name: 'sdk-wave',
  description: 'SDK-context wave executor: todos redteam → tier-parallel implement → unit/phase redteam → protocol audit → codify → archive. All harness agentTypes are used: redteam, python-implementer, debug, codify (populated in harness/agents/core/ since 2026-06-16), plus advisor agentTypes (a2a-advisor etc.).',
  phases: [
    { title: 'Parse',          detail: 'Read wave file; extract groups, creates paths, groupDeps, LRN baseline' },
    { title: 'Todos Redteam',  detail: 'Redteam the wave plan: SI risk annotation, registry reuse (Reuses: C-NNN), new component candidate flagging' },
    { title: 'Implement',      detail: 'Tier-based parallel fan-out (groupDeps); scoped pytest per todo; no full-suite run until gate' },
    { title: 'Unit Redteam',   detail: 'Per-group zero-tolerance fix loop (max 5 rounds; debug fires after >3 failed rounds and on stall)' },
    { title: 'Phase Redteam',  detail: 'Full-wave zero-tolerance fix loop (max 8 rounds; debug fires after >3 failed rounds and on stall)' },
    { title: 'Protocol Audit', detail: 'a2a-advisor / mcp-advisor / ag-ui-advisor / a2ui-advisor in parallel (only for touched protocol surfaces) + seam check' },
    { title: 'Codify',         detail: 'SDK issue scan → parallel LRN capture → README index → C-NNN registration' },
    { title: 'Archive',        detail: 'Pre-archive pytest gate + commit-intent guard (GH-40/GH-84) → move to completed/ → update plan.md' },
  ],
}

// ─── args ─────────────────────────────────────────────────────────────────────
// args.waveFile : absolute path to the active wave file
// args.today    : ISO date string (e.g. "2026-06-16")
const WAVE_FILE = args.waveFile
const TODAY     = args.today || '(see context date)'

// ─── protocol surface paths — SDK repo layout ─────────────────────────────────
const A2A_SURFACE  = ['agent_sdk/routes/a2a', 'agent_sdk/routes/agent_card', 'agent_sdk/models/a2a']
const MCP_SURFACE  = ['agent_sdk/routes/mcp', 'agent_sdk/routes/oauth']
const AGUI_SURFACE = ['agent_sdk/routes/ag_ui']
const A2UI_SURFACE = ['agent_sdk/a2ui/', 'agent_sdk/models/content_types']

// ─── schemas ──────────────────────────────────────────────────────────────────

const WAVE_SCHEMA = {
  type: 'object',
  required: ['waveId', 'allCreates', 'allModifies', 'groups', 'groupDeps', 'lrnNext'],
  additionalProperties: false,
  properties: {
    waveId:      { type: 'string' },
    allCreates:  { type: 'array', items: { type: 'string' } },
    allModifies: { type: 'array', items: { type: 'string' } },
    lrnNext:     { type: 'integer' },
    groupDeps: {
      type: 'object',
      description: 'Maps group label to the labels of OTHER groups it depends on (empty array = no external deps)',
      additionalProperties: { type: 'array', items: { type: 'string' } },
    },
    groups: {
      type: 'array',
      items: {
        type: 'object',
        required: ['label', 'creates', 'modifies', 'todos'],
        additionalProperties: false,
        properties: {
          label:    { type: 'string' },
          creates:  { type: 'array', items: { type: 'string' } },
          modifies: { type: 'array', items: { type: 'string' } },
          todos: {
            type: 'array',
            items: {
              type: 'object',
              required: ['id', 'title', 'body'],
              additionalProperties: false,
              properties: {
                id:    { type: 'string' },
                title: { type: 'string' },
                body:  { type: 'string' },
              },
            },
          },
        },
      },
    },
  },
}

const RT_SCHEMA = {
  type: 'object',
  required: ['findingsCount', 'findings'],
  additionalProperties: false,
  properties: {
    findingsCount: { type: 'integer' },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        required: ['id', 'severity', 'file', 'description', 'fix'],
        additionalProperties: false,
        properties: {
          id:           { type: 'string' },
          severity:     { type: 'string', enum: ['critical', 'high', 'medium', 'low'] },
          file:         { type: 'string' },
          description:  { type: 'string' },
          fix:          { type: 'string' },
          codify:       { type: 'string' },
          sdkCandidate: { type: 'boolean' },
        },
      },
    },
  },
}

const PROTO_SCHEMA = {
  type: 'object',
  required: ['criticalCount', 'highCount', 'findings'],
  additionalProperties: false,
  properties: {
    criticalCount: { type: 'integer' },
    highCount:     { type: 'integer' },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        required: ['protocol', 'severity', 'rule', 'description'],
        additionalProperties: false,
        properties: {
          protocol:    { type: 'string', enum: ['A2A', 'MCP', 'AG-UI', 'A2UI', 'SEAM'] },
          severity:    { type: 'string', enum: ['critical', 'high', 'medium', 'low'] },
          rule:        { type: 'string' },
          description: { type: 'string' },
          fix:         { type: 'string' },
          codify:      { type: 'string' },
        },
      },
    },
  },
}

const PLAN_RT_SCHEMA = {
  type: 'object',
  required: ['issuesFound', 'reuseAnnotations', 'siAnnotations', 'sliceIssues', 'newCandidates'],
  additionalProperties: false,
  properties: {
    issuesFound: { type: 'boolean' },
    reuseAnnotations: {
      type: 'array',
      items: {
        type: 'object',
        required: ['todoId', 'componentId', 'note'],
        additionalProperties: false,
        properties: {
          todoId:      { type: 'string' },
          componentId: { type: 'string' },
          note:        { type: 'string' },
        },
      },
    },
    siAnnotations: {
      type: 'array',
      items: {
        type: 'object',
        required: ['todoId', 'siId', 'note'],
        additionalProperties: false,
        properties: {
          todoId: { type: 'string' },
          siId:   { type: 'string' },
          note:   { type: 'string' },
        },
      },
    },
    sliceIssues: {
      type: 'array',
      items: {
        type: 'object',
        required: ['todoId', 'issue'],
        additionalProperties: false,
        properties: {
          todoId: { type: 'string' },
          issue:  { type: 'string' },
        },
      },
    },
    newCandidates: {
      type: 'array',
      items: {
        type: 'object',
        required: ['name', 'location', 'description'],
        additionalProperties: false,
        properties: {
          name:        { type: 'string' },
          location:    { type: 'string' },
          description: { type: 'string' },
        },
      },
    },
  },
}

const SDK_SCAN_SCHEMA = {
  type: 'object',
  required: ['sdkCandidates'],
  additionalProperties: false,
  properties: {
    sdkCandidates: {
      type: 'array',
      items: {
        type: 'object',
        required: ['description', 'severity', 'component', 'rationale'],
        additionalProperties: false,
        properties: {
          description: { type: 'string' },
          severity:    { type: 'string' },
          component:   { type: 'string' },
          rationale:   { type: 'string' },
          file:        { type: 'string' },
        },
      },
    },
  },
}

const GATE_SCHEMA = {
  type: 'object',
  required: ['exitCode', 'passCount', 'failCount', 'failures'],
  additionalProperties: false,
  properties: {
    exitCode:  { type: 'number' },
    passCount: { type: 'number' },
    failCount: { type: 'number' },
    failures:  { type: 'array', items: { type: 'string' } },
  },
}

// GH-84: archive intent schema — git status check before archive
// The agent runs `git status --short` in the SDK repo, parses the output into dirty paths,
// cross-references against wave.allScope (Creates: ∪ Modifies:) for offendingPaths, and
// separately flags any dirty/untracked paths under harness deliverable directories
// (tests/, workspace/learning/, workspace/scenarios/results/, workspace/prd/) as offendingHarnessPaths.
const ARCHIVE_INTENT_SCHEMA = {
  type: 'object',
  required: ['gitStatusOutput', 'dirtyPaths', 'offendingPaths', 'offendingHarnessPaths'],
  additionalProperties: false,
  properties: {
    gitStatusOutput:      { type: 'string', description: 'Raw stdout of git status --short' },
    dirtyPaths:           { type: 'array', items: { type: 'string' }, description: 'All paths reported dirty or untracked by git' },
    offendingPaths:       { type: 'array', items: { type: 'string' }, description: 'Dirty paths that overlap with wave.allScope (Creates: ∪ Modifies:)' },
    offendingHarnessPaths: { type: 'array', items: { type: 'string' }, description: 'Dirty/untracked paths under tests/, workspace/learning/, workspace/scenarios/results/, or workspace/prd/ even if not in allScope' },
  },
}

// ─── helpers ──────────────────────────────────────────────────────────────────

function sigs(findings) {
  return new Set(findings.map(function(f) { return f.file + ':' + f.description }))
}

function sigsEqual(a, b) {
  if (a.size !== b.size) return false
  for (const k of a) { if (!b.has(k)) return false }
  return true
}

// ─── state ────────────────────────────────────────────────────────────────────
let registryCandidates  = []
let sdkCandidatesCount  = 0

// ─── phase 0: parse wave file ─────────────────────────────────────────────────
phase('Parse')

const wave = await agent(
  'Read the wave file at: ' + WAVE_FILE + '\n\n' +
  'Also read workspace/learning/README.md to find the highest LRN number ' +
  '(e.g. LRN-023 → lrnNext = 24; if none, lrnNext = 1).\n\n' +
  'Extract:\n' +
  '- waveId: the w[NNN] identifier from the filename\n' +
  '- allCreates: every "Creates:" path listed across all todos in this wave\n' +
  '- allModifies: every "Modifies:" path listed across all todos in this wave.\n' +
  '  EXCLUDE any todo marked [~] (out-of-repo / cannot land here) and any path\n' +
  '  that resolves to another repo — only in-repo paths count as wave scope.\n' +
  '  A wave whose only paths are Modifies: (no Creates:) is legitimate, not a bug.\n' +
  '- lrnNext: highest existing LRN number + 1\n' +
  '- groups: execution groups (Depends: respected). Each group MUST carry both its\n' +
  '  own creates (Creates: paths) and modifies (Modifies: paths, in-repo only).\n' +
  '  Todos without ‖ group: get label "ungrouped-N" (N = position).\n' +
  '  Same ‖ group: label → same group entry.\n' +
  '  Do NOT impose a sequential ordering — let groupDeps express ordering instead.\n' +
  '- groupDeps: for each group label, list the labels of OTHER groups whose todos\n' +
  '  appear in any `Depends:` field of this group\'s todos.\n' +
  '  A group with no external Depends: references maps to [].\n' +
  '  Format: {"A": [], "B": ["A"], ...}\n\n' +
  'Return structured data.',
  { schema: WAVE_SCHEMA, label: 'parse', phase: 'Parse' }
)

if (!wave) {
  log('ERROR: could not parse wave file at ' + WAVE_FILE)
  return { error: 'parse-failed' }
}

if (!wave.waveId) {
  log('ERROR: wave file parsed but waveId is undefined — aborting (harness bug, not a clean wave)')
  return { error: 'missing-wave-id' }
}

// Unified review scope = Creates: ∪ Modifies: paths. Modify-only waves (0 Creates,
// >0 Modifies) are legitimate (e.g. skill/doc-only waves) — deriving scope from
// Creates: alone false-aborts them here AND lands them with empty adversarial-review
// and protocol-audit scope downstream. Always union both. (RT-002 / LRN below)
function uniq(xs) { return Array.from(new Set(xs || [])) }

wave.allCreates  = uniq(wave.allCreates)
wave.allModifies = uniq(wave.allModifies)
wave.allScope    = uniq(wave.allCreates.concat(wave.allModifies))
for (const g of wave.groups) {
  g.creates  = uniq(g.creates)
  g.modifies = uniq(g.modifies)
  g.scope    = uniq(g.creates.concat(g.modifies))
}

if (wave.allScope.length === 0) {
  log('ERROR: wave ' + wave.waveId + ' has no Creates: AND no Modifies: paths — aborting ' +
      '(truly empty scope is a harness bug, not a clean wave)')
  return { error: 'empty-scope', waveId: wave.waveId }
}

log('Wave ' + wave.waveId + ': ' + wave.groups.length + ' group(s), ' +
    wave.allScope.length + ' scope path(s) (' + wave.allCreates.length + ' create / ' +
    wave.allModifies.length + ' modify), lrnNext=' + wave.lrnNext)

const lrnBase         = wave.lrnNext
const allHighFindings = []
let   protocolBlocked    = false
let   testsBlockedArchive = false   // RT-003: tracks when a red test suite (not protocol) blocks archive
let   testsRed            = false
let   totalTodos          = 0

// ─── phase 1: todos redteam ───────────────────────────────────────────────────
phase('Todos Redteam')

const planRt = await agent(
  'Review the todo plan for wave ' + wave.waveId + ' BEFORE implementation starts.\n\n' +
  'Wave file: ' + WAVE_FILE + '\n' +
  'Also read:\n' +
  '  - workspace/components/README.md  (C-NNN registry)\n' +
  '  - workspace/learning/README.md    (past learnings + Prevention clauses)\n\n' +
  'Check ONLY these four things:\n' +
  '1. REGISTRY REUSE — does a C-NNN component already cover this todo\'s capability?\n' +
  '   If yes, add to reuseAnnotations.\n' +
  '2. SI RISK — does this todo touch auth, credential, or transport code?\n' +
  '   If yes and SI: field is absent, add to siAnnotations.\n' +
  '3. VERTICAL SLICE — is this todo a horizontal layer instead of an end-to-end\n' +
  '   deliverable? Add to sliceIssues only if genuinely non-vertical.\n' +
  '4. NEW COMPONENT CANDIDATES — would any planned code be reusable across\n' +
  '   multiple agents or waves? Add name/location/description to newCandidates.\n\n' +
  'If the plan is already clean, issuesFound=false and all arrays empty.\n' +
  'Return structured output.',
  { schema: PLAN_RT_SCHEMA, label: 'rt:todos', phase: 'Todos Redteam', agentType: 'redteam' }
)

if (planRt) {
  registryCandidates = planRt.newCandidates || []

  if (!planRt.issuesFound) {
    log('Todos plan clean — proceeding directly to implementation')
  } else {
    const hasAnnotations = (planRt.reuseAnnotations && planRt.reuseAnnotations.length > 0) ||
                           (planRt.siAnnotations    && planRt.siAnnotations.length > 0)
    const hasSliceIssues = planRt.sliceIssues && planRt.sliceIssues.length > 0

    if (hasSliceIssues) {
      log('Todos Redteam: ' + planRt.sliceIssues.length + ' slice issue(s) — logged (not blocking)')
      planRt.sliceIssues.forEach(function(s) { log('  [slice] ' + s.todoId + ': ' + s.issue) })
    }

    if (registryCandidates.length > 0) {
      log('Todos Redteam: ' + registryCandidates.length + ' new component candidate(s) flagged')
    }

    if (hasAnnotations) {
      log('Todos Redteam: writing SI and registry annotations back to wave file before implement')
      await agent(
        'Annotate the wave file ' + WAVE_FILE + ' with these additions.\n\n' +
        'Registry reuse (add `Reuses: <componentId>` to the matching todo body):\n' +
        JSON.stringify(planRt.reuseAnnotations, null, 2) + '\n\n' +
        'SI risk (add `SI: <siId>  # <note>` to the matching todo body):\n' +
        JSON.stringify(planRt.siAnnotations, null, 2) + '\n\n' +
        'Rules:\n' +
        '- Match todo by its backtick-wrapped ID on the checkbox line\n' +
        '- Append annotation lines after the last indented field of that todo block\n' +
        '- Preserve all whitespace and structure\n\n' +
        'Report: which todos were annotated.',
        { label: 'rt:todos:annotate', phase: 'Todos Redteam' }
      )
    }
  }
} else {
  log('Todos Redteam agent returned null — proceeding to implementation')
}

// ─── phase 2: implement (tier-based parallel) ─────────────────────────────────
phase('Implement')

const completedGroups = new Set()
const remainingGroups = wave.groups.slice()

while (remainingGroups.length > 0) {
  const readyGroups = remainingGroups.filter(function(g) {
    const deps = (wave.groupDeps && wave.groupDeps[g.label]) || []
    return deps.every(function(dep) { return completedGroups.has(dep) })
  })

  if (readyGroups.length === 0) {
    log('WARNING: unresolvable group dependency; falling back to sequential for group ' + remainingGroups[0].label)
    readyGroups.push(remainingGroups[0])
  }

  for (const rg of readyGroups) {
    const idx = remainingGroups.findIndex(function(g) { return g.label === rg.label })
    if (idx !== -1) remainingGroups.splice(idx, 1)
  }

  const tierLabel = readyGroups.map(function(g) { return g.label }).join(', ')
  totalTodos += readyGroups.reduce(function(n, g) { return n + g.todos.length }, 0)

  if (readyGroups.length > 1) {
    log('Implementing ' + readyGroups.length + ' groups in parallel: ' + tierLabel)
  }

  function makeGroupThunk(group) {
    return function() {
      log('Implementing group ' + group.label + ' (' + group.todos.length + ' todo(s))')
      if (group.todos.length === 1) {
        const todo = group.todos[0]
        return agent(
          'Implement this SDK todo. Read the relevant source files before making changes.\n\n' +
          'Context: this is the a2a-sdk repo — public API must not break (no new required\n' +
          'params on existing functions), type annotations must be correct (mypy runs at\n' +
          'release), and tests must pass.\n\n' +
          'Test-first for correctness-bearing code: write failing test FIRST (RED),\n' +
          'then implement (GREEN), then refactor. Do NOT run the full test suite —\n' +
          'run only the test file for your changes:\n' +
          '  .venv/bin/pytest -q tests/<your-test-file>.py\n\n' +
          'Todo:\n' + todo.body + '\n\n' +
          'Report: files created/modified, RED→GREEN confirmation, any blockers.',
          { label: 'impl:' + todo.id, phase: 'Implement', agentType: 'python-implementer' }
        )
      } else {
        return parallel(group.todos.map(function(todo) {
          return function() {
            return agent(
              'Implement this SDK todo. Read the relevant source files before making changes.\n\n' +
              'Context: this is the a2a-sdk repo — public API must not break, type annotations\n' +
              'must be correct, and tests must pass.\n\n' +
              'Test-first: write failing test FIRST (RED), then implement (GREEN). Run only\n' +
              'your test file: `.venv/bin/pytest -q tests/<your-test-file>.py`\n\n' +
              'Todo:\n' + todo.body + '\n\n' +
              'Report: files created/modified, RED→GREEN confirmation.',
              { label: 'impl:' + todo.id, phase: 'Implement', agentType: 'python-implementer' }
            )
          }
        }))
      }
    }
  }

  if (readyGroups.length === 1) {
    await makeGroupThunk(readyGroups[0])()
  } else {
    await parallel(readyGroups.map(makeGroupThunk))
  }

  for (const rg of readyGroups) completedGroups.add(rg.label)
}

// ─── phase 3: unit redteam ────────────────────────────────────────────────────
phase('Unit Redteam')

for (const group of wave.groups) {
  log('Unit redteam — group ' + group.label)
  let uRound   = 0
  let prevSigs = new Set()

  while (true) {
    uRound++

    const rt = await agent(
      'Adversarial review of the SDK files created/modified by group ' + group.label + '.\n\n' +
      'Scope (Creates: AND Modifies: paths for this group):\n' + group.scope.join('\n') + '\n\n' +
      'Also check their transitive callers and importers within agent_sdk/.\n\n' +
      'Review dimensions: spec/protocol conformance, type correctness, test coverage,\n' +
      'public API stability (no breaking changes), error handling, code quality.\n' +
      'Dimension 5: no partial implementations, stubs, TODOs, or placeholder returns —\n' +
      'every AC in the todo body must be satisfied in the landed code.\n' +
      'For protocol routes (agent_sdk/routes/): check HTTP status codes, wire shapes,\n' +
      'spec version gating, and spec citations.\n\n' +
      'Return structured findings.',
      { schema: RT_SCHEMA, label: 'rt:unit:' + group.label + ':r' + uRound, phase: 'Unit Redteam',
        agentType: 'redteam' }
    )

    if (!rt || rt.findingsCount === 0) {
      log('Group ' + group.label + ' clean at round ' + uRound)
      break
    }

    log('Group ' + group.label + ' round ' + uRound + ': ' + rt.findingsCount + ' finding(s)')

    const curSigs = sigs(rt.findings)
    const stalled = uRound > 1 && sigsEqual(curSigs, prevSigs)

    if (uRound >= 5) {
      log('Round budget exhausted for group ' + group.label + ' — deferring')
      await agent(
        'Write workspace/todos/deferred/' + wave.waveId + '-group-' + group.label + '-budget-exhausted.md\n\n' +
        'Include: wave ID (' + wave.waveId + '), group (' + group.label + '), date (' + TODAY + '),\n' +
        'round count (' + uRound + '), and the final findings:\n' +
        JSON.stringify(rt.findings, null, 2) + '\n\n' +
        'Instruction: "Fix remaining findings, then re-run /wave ' + wave.waveId + '".',
        { label: 'defer:unit:' + group.label, phase: 'Unit Redteam' }
      )
      break
    }

    if (uRound > 3 || stalled) {
      log((stalled ? 'Stall detected — ' : 'Round 4+ — ') + 'escalating to fresh-lens analysis')
      await agent(
        'Fix-loop requires fresh-lens analysis' + (stalled ? ' (stalled)' : ' (round ' + uRound + ')') + '.\n\n' +
        'Prior findings:\n' + JSON.stringify(rt.findings, null, 2) + '\n\n' +
        'Scope:\n' + group.scope.join('\n') + '\n\n' +
        'Read code cold. Diagnose root cause. Fix at the root.',
        { label: 'debug:unit:' + group.label + ':r' + uRound, phase: 'Unit Redteam', agentType: 'debug' }
      )
    }
    prevSigs = curSigs

    const byFile = {}
    for (const f of rt.findings) {
      if (!byFile[f.file]) byFile[f.file] = []
      byFile[f.file].push(f)
    }

    const fixTasks = Object.keys(byFile).map(function(file) {
      return function() {
        return agent(
          'Fix these findings in ' + file + ':\n\n' +
          JSON.stringify(byFile[file], null, 2) + '\n\n' +
          'Run `.venv/bin/pytest -q tests/` (scoped to changed files) after fixing.',
          { label: 'fix:unit:' + group.label + ':r' + uRound + ':' + file.replace(/\//g, '-'),
            phase: 'Unit Redteam', agentType: 'python-implementer' }
        )
      }
    })

    const highFindings = rt.findings.filter(function(f) {
      return (f.severity === 'critical' || f.severity === 'high') && f.codify
    })
    allHighFindings.push.apply(allHighFindings, highFindings)
    await parallel(fixTasks)

    const unitGate = await agent(
      'Run: .venv/bin/pytest -q tests/\n' +
      'Report: exitCode (0=pass, non-zero=fail), passCount, failCount, and failures (list of\n' +
      '"test_file.py::test_name: reason" for each failing test). Return all fields.',
      { schema: GATE_SCHEMA, label: 'gate:unit:' + group.label + ':r' + uRound, phase: 'Unit Redteam' }
    )
    if (unitGate && unitGate.exitCode !== 0) {
      testsRed = true
      log('Gate RED (' + unitGate.failCount + ' failing) — dispatching test-fix agent')
      await agent(
        'Fix the failing tests. Read the test file and the source it covers.\n' +
        'Failing tests:\n' + unitGate.failures.join('\n') + '\n\n' +
        'Run `.venv/bin/pytest -q <failing-test-file>` to confirm GREEN before finishing.',
        { label: 'fix:tests:unit:' + group.label + ':r' + uRound, phase: 'Unit Redteam' }
      )
    }
  }
}

// ─── phase 4: phase redteam ───────────────────────────────────────────────────
phase('Phase Redteam')

if (!wave.allScope || wave.allScope.length === 0) {
  log('ERROR: phase redteam aborted — scope (Creates: ∪ Modifies:) is empty (a harness bug, not a clean wave)')
  return { error: 'empty-scope-phase-redteam', waveId: wave.waveId }
}

let pRound   = 0
let prevSigs = new Set()

while (true) {
  pRound++

  const rt = await agent(
    'Adversarial review of the full wave ' + wave.waveId + ' in the a2a-sdk repo.\n\n' +
    'Scope (all Creates: AND Modifies: paths):\n' + wave.allScope.join('\n') + '\n\n' +
    'Also check transitive callers and importers. Re-expand scope every round.\n\n' +
    'Review dimensions: protocol spec conformance, type correctness, test coverage,\n' +
    'public API stability, error handling, code quality, backward compatibility.\n' +
    'Dimension 5: no partial implementations, stubs, TODOs, or placeholder returns —\n' +
    'every AC in the todo body must be satisfied in the landed code.\n\n' +
    'Return structured findings.',
    { schema: RT_SCHEMA, label: 'rt:phase:r' + pRound, phase: 'Phase Redteam', agentType: 'redteam' }
  )

  if (!rt || rt.findingsCount === 0) {
    log('Phase redteam clean at round ' + pRound)
    break
  }

  log('Phase redteam round ' + pRound + ': ' + rt.findingsCount + ' finding(s)')

  const curSigs = sigs(rt.findings)
  const pStalled = pRound > 1 && sigsEqual(curSigs, prevSigs)

  if (pRound >= 8) {
    log('Phase round budget exhausted — continuing to Protocol Audit')
    break
  }

  if (pRound > 3 || pStalled) {
    log((pStalled ? 'Stall detected — ' : 'Round 4+ — ') + 'escalating to fresh-lens analysis')
    await agent(
      'Phase fix-loop requires fresh-lens analysis' + (pStalled ? ' (stalled)' : ' (round ' + pRound + ')') + '.\n\n' +
      'Findings:\n' + JSON.stringify(rt.findings, null, 2) + '\n\n' +
      'Scope:\n' + wave.allScope.join('\n') + '\n\n' +
      'Read cold; diagnose; fix at root.',
      { label: 'debug:phase:r' + pRound, phase: 'Phase Redteam', agentType: 'debug' }
    )
  }
  prevSigs = curSigs

  const byFile = {}
  for (const f of rt.findings) {
    if (!byFile[f.file]) byFile[f.file] = []
    byFile[f.file].push(f)
  }

  const fixTasks = Object.keys(byFile).map(function(file) {
    return function() {
      return agent(
        'Fix findings in ' + file + ':\n\n' + JSON.stringify(byFile[file], null, 2) + '\n\n' +
        'Run `.venv/bin/pytest -q tests/` after fixing.',
        { label: 'fix:phase:r' + pRound + ':' + file.replace(/\//g, '-'), phase: 'Phase Redteam',
          agentType: 'python-implementer' }
      )
    }
  })

  const highFindings = rt.findings.filter(function(f) {
    return (f.severity === 'critical' || f.severity === 'high') && f.codify
  })
  allHighFindings.push.apply(allHighFindings, highFindings)
  await parallel(fixTasks)

  const phaseGate = await agent(
    'Run: .venv/bin/pytest -q tests/\n' +
    'Report: exitCode (0=pass, non-zero=fail), passCount, failCount, and failures. Return all fields.',
    { schema: GATE_SCHEMA, label: 'gate:phase:r' + pRound, phase: 'Phase Redteam' }
  )
  if (phaseGate && phaseGate.exitCode !== 0) {
    testsRed = true
    log('Gate RED (' + phaseGate.failCount + ' failing) — dispatching test-fix agent')
    await agent(
      'Fix the failing tests.\n' +
      'Failing tests:\n' + phaseGate.failures.join('\n') + '\n\n' +
      'Run `.venv/bin/pytest -q <failing-test-file>` to confirm GREEN.',
      { label: 'fix:tests:phase:r' + pRound, phase: 'Phase Redteam' }
    )
  }
}

// ─── phase 5: protocol audit ──────────────────────────────────────────────────
phase('Protocol Audit')

// Protocol-surface detection must scan the full scope (Creates: ∪ Modifies:):
// a modify-only wave that edits a route file still needs its protocol audit.
const runA2A  = wave.allScope.some(function(p) {
  return A2A_SURFACE.some(function(pp) { return p.indexOf(pp) !== -1 })
})
const runMCP  = wave.allScope.some(function(p) {
  return MCP_SURFACE.some(function(pp) { return p.indexOf(pp) !== -1 })
})
const runAGUI = wave.allScope.some(function(p) {
  return AGUI_SURFACE.some(function(pp) { return p.indexOf(pp) !== -1 })
})
const runA2UI = wave.allScope.some(function(p) {
  return A2UI_SURFACE.some(function(pp) { return p.indexOf(pp) !== -1 })
})
const runProtocol = runA2A || runMCP || runAGUI || runA2UI

if (!runProtocol) {
  log('Protocol audit skipped — no protocol surfaces in scope (Creates: ∪ Modifies:)')
} else {
  log('Protocol audit triggered (A2A=' + runA2A + ' MCP=' + runMCP + ' AG-UI=' + runAGUI + ' A2UI=' + runA2UI + ')')

  const advisorTasks = []

  if (runA2A) {
    advisorTasks.push(function() {
      return agent(
        'A2A v0.3.0 conformance audit of the SDK routes.\n\n' +
        'Files to audit:\n' +
        wave.allScope.filter(function(p) {
          return A2A_SURFACE.some(function(pp) { return p.indexOf(pp) !== -1 })
        }).join('\n') + '\n\n' +
        'Check: agent card shape, task/message/part/artifact shapes, streaming,\n' +
        'error codes (-32001 through -32007 → correct HTTP status), auth surface.\n\n' +
        'Return structured findings. Set protocol="A2A" per finding.',
        { schema: PROTO_SCHEMA, agentType: 'a2a-advisor', label: 'proto:a2a', phase: 'Protocol Audit' }
      )
    })
  }

  if (runMCP) {
    advisorTasks.push(function() {
      return agent(
        'MCP server + Claude.ai connector conformance audit.\n\n' +
        'Files to audit:\n' +
        wave.allScope.filter(function(p) {
          return MCP_SURFACE.some(function(pp) { return p.indexOf(pp) !== -1 })
        }).join('\n') + '\n\n' +
        'Check: Streamable-HTTP transport, OAuth 2.1 discovery chain,\n' +
        'PKCE S256, token aud binding, CORS, initialize echo (protocolVersion gating),\n' +
        'serverInfo.title version gating (present only at 2025-11-25+, absent at 2025-06-18),\n' +
        'SUPPORTED_PROTOCOL_VERSIONS list, tools/list shape, isError vs JSON-RPC error split.\n\n' +
        'Return structured findings. Set protocol="MCP" per finding.',
        { schema: PROTO_SCHEMA, agentType: 'mcp-advisor', label: 'proto:mcp', phase: 'Protocol Audit' }
      )
    })
  }

  if (runAGUI) {
    advisorTasks.push(function() {
      return agent(
        'AG-UI conformance audit.\n\n' +
        'Files to audit:\n' +
        wave.allScope.filter(function(p) {
          return AGUI_SURFACE.some(function(pp) { return p.indexOf(pp) !== -1 })
        }).join('\n') + '\n\n' +
        'Check: SSE event catalog (34 types), RunAgentInput schema, camelCase wire,\n' +
        'RUN_STARTED first / RUN_FINISHED last, CUSTOM event spec, bare data: frames.\n\n' +
        'Return structured findings. Set protocol="AG-UI" per finding.',
        { schema: PROTO_SCHEMA, agentType: 'ag-ui-advisor', label: 'proto:agui', phase: 'Protocol Audit' }
      )
    })
  }

  if (runA2UI) {
    advisorTasks.push(function() {
      return agent(
        'A2UI v0.9.1 + Standard Profile v1 conformance audit.\n\n' +
        'Files to audit:\n' +
        wave.allScope.filter(function(p) {
          return A2UI_SURFACE.some(function(pp) { return p.indexOf(pp) !== -1 })
        }).join('\n') + '\n\n' +
        'Check: createSurface/updateComponents/updateDataModel/deleteSurface shapes,\n' +
        'Standard Profile types, JSON-Pointer binding, A2A DataPart delivery,\n' +
        'compact schema accuracy (? marks on optional fields only), field contracts.\n\n' +
        'Return structured findings. Set protocol="A2UI" per finding.',
        { schema: PROTO_SCHEMA, agentType: 'a2ui-advisor', label: 'proto:a2ui', phase: 'Protocol Audit' }
      )
    })
  }

  advisorTasks.push(function() {
    return agent(
      'Cross-protocol seam audit — consistency ACROSS protocol surfaces in the SDK.\n\n' +
      'Read: agent_sdk/routes/ directory and any route files in the scope list.\n\n' +
      'Wave scope paths (Creates: ∪ Modifies:):\n' + wave.allScope.join('\n') + '\n\n' +
      'Check:\n' +
      '- MCP version negotiation drives which fields appear (e.g. serverInfo.title gating)\n' +
      '- Auth mode enforced uniformly across A2A, MCP, AG-UI surfaces\n' +
      '- Version strings consistent across routes\n' +
      '- No tool advertised that is absent from the registry\n\n' +
      'Return structured findings. Set protocol="SEAM" per finding.',
      { schema: PROTO_SCHEMA, label: 'proto:seam', phase: 'Protocol Audit' }
    )
  })

  const protoResults = (await parallel(advisorTasks)).filter(Boolean)
  let protoCritical = protoResults.reduce(function(n, r) { return n + (r.criticalCount || 0) }, 0)
  const protoHigh   = protoResults.reduce(function(n, r) { return n + (r.highCount || 0) }, 0)
  const allProtoFindings = protoResults.reduce(function(acc, r) {
    return acc.concat(r.findings || [])
  }, [])

  log('Protocol audit: ' + protoCritical + ' critical, ' + protoHigh + ' high')

  allHighFindings.push.apply(allHighFindings,
    allProtoFindings.filter(function(f) {
      return (f.severity === 'critical' || f.severity === 'high') && f.codify
    }).map(function(f) {
      return {
        id:          'proto-' + f.protocol + '-' + f.rule.replace(/[^a-z0-9]/gi, '-').toLowerCase(),
        severity:    f.severity,
        file:        'protocol-surface',
        description: f.description,
        fix:         f.fix || ('See protocol-audit findings for ' + f.protocol + ' rule ' + f.rule),
        codify:      f.codify,
      }
    })
  )

  if (protoCritical > 0) {
    log('Critical protocol findings — dispatching fix agent')
    await agent(
      'Fix ALL critical protocol conformance findings below. These block archive.\n\n' +
      'Findings:\n' + JSON.stringify(
        allProtoFindings.filter(function(f) { return f.severity === 'critical' }),
        null, 2
      ) + '\n\n' +
      'Run `.venv/bin/pytest -q tests/` after fixing. Report files changed.',
      { label: 'proto:fix', phase: 'Protocol Audit', agentType: 'python-implementer' }
    )

    const protoFixGate = await agent(
      'Run: .venv/bin/pytest -q tests/\n' +
      'Report: exitCode (0=pass, non-zero=fail), passCount, failCount, failures. Return all fields.',
      { schema: GATE_SCHEMA, label: 'gate:proto:fix', phase: 'Protocol Audit' }
    )
    if (protoFixGate && protoFixGate.exitCode !== 0) {
      testsRed = true
      log('Gate RED after proto:fix — dispatching test-fix agent')
      await agent(
        'Fix the failing tests introduced by the protocol fix.\n' +
        'Failing tests:\n' + protoFixGate.failures.join('\n') + '\n\n' +
        'Run `.venv/bin/pytest -q <failing-test-file>` to confirm GREEN.',
        { label: 'fix:tests:proto:fix', phase: 'Protocol Audit' }
      )
    }

    const recheckTasks = []
    if (runA2A) {
      recheckTasks.push(function() {
        return agent(
          'A2A re-audit after preceding fix.\n' +
          'Scope paths (Creates: ∪ Modifies:):\n' + wave.allScope.join('\n') + '\n' +
          'Focus on previously-critical findings. Return structured findings.',
          { schema: PROTO_SCHEMA, agentType: 'a2a-advisor', label: 'proto:recheck:a2a', phase: 'Protocol Audit' }
        )
      })
    }
    if (runMCP) {
      recheckTasks.push(function() {
        return agent(
          'MCP re-audit after preceding fix.\n' +
          'Scope paths (Creates: ∪ Modifies:):\n' + wave.allScope.join('\n') + '\n' +
          'Focus on previously-critical findings. Return structured findings.',
          { schema: PROTO_SCHEMA, agentType: 'mcp-advisor', label: 'proto:recheck:mcp', phase: 'Protocol Audit' }
        )
      })
    }
    if (runAGUI) {
      recheckTasks.push(function() {
        return agent(
          'AG-UI re-audit after preceding fix.\n' +
          'Scope paths (Creates: ∪ Modifies:):\n' + wave.allScope.join('\n') + '\n' +
          'Focus on previously-critical findings. Return structured findings.',
          { schema: PROTO_SCHEMA, agentType: 'ag-ui-advisor', label: 'proto:recheck:agui', phase: 'Protocol Audit' }
        )
      })
    }
    if (runA2UI) {
      recheckTasks.push(function() {
        return agent(
          'A2UI re-audit after preceding fix.\n' +
          'Scope paths (Creates: ∪ Modifies:):\n' + wave.allScope.join('\n') + '\n' +
          'Focus on previously-critical findings. Return structured findings.',
          { schema: PROTO_SCHEMA, agentType: 'a2ui-advisor', label: 'proto:recheck:a2ui', phase: 'Protocol Audit' }
        )
      })
    }
    recheckTasks.push(function() {
      return agent(
        'Cross-protocol seam re-audit after preceding fix.\n' +
        'Scope paths (Creates: ∪ Modifies:):\n' + wave.allScope.join('\n') + '\n' +
        'Focus on previously-critical SEAM findings. Return structured findings.',
        { schema: PROTO_SCHEMA, label: 'proto:recheck:seam', phase: 'Protocol Audit' }
      )
    })
    const recheckResults = (await parallel(recheckTasks)).filter(Boolean)
    protoCritical = recheckResults.reduce(function(n, r) { return n + (r.criticalCount || 0) }, 0)

    if (protoCritical > 0) {
      log('BLOCKED — critical protocol findings persist; wave will not archive')
      protocolBlocked = true
      await agent(
        'Write workspace/todos/deferred/' + wave.waveId + '-protocol-blocked.md\n\n' +
        'Include: wave ID (' + wave.waveId + '), date (' + TODAY + '), unresolved critical\n' +
        'findings from the recheck, and the instruction:\n' +
        '"Fix protocol findings, then re-run /wave ' + wave.waveId + '".',
        { label: 'proto:defer-note', phase: 'Protocol Audit' }
      )
    }
  }
}

// ─── phase 6: codify ──────────────────────────────────────────────────────────
phase('Codify')

const seenKeys  = new Set()
const toCodeify = []
for (const f of allHighFindings) {
  const key = f.file + ':' + f.description
  if (!seenKeys.has(key)) {
    seenKeys.add(key)
    toCodeify.push(f)
  }
}

log('Codifying ' + toCodeify.length + ' critical/high finding(s)')

if (toCodeify.length > 0) {
  const sdkScan = await agent(
    'Classify each finding as SDK-level or agent-domain.\n\n' +
    'SDK-LEVEL (include): harness/skills, harness/workflows, SDK internals (Agent, ToolSet,\n' +
    'SourceAdapter, credential store), protocol routes (agent_sdk/routes/), A2UI catalog,\n' +
    'content_types models, template scaffold, security.\n\n' +
    'AGENT-DOMAIN (exclude): agent-specific tool code, domain adapters, agent tests.\n\n' +
    'For each SDK-level finding, assign a component:\n' +
    'harness/skill | harness/workflow | harness/agent | harness/template |\n' +
    'sdk/build | sdk/loop | sdk/credentials | sdk/console |\n' +
    'protocol/a2a | protocol/mcp | protocol/ag-ui | protocol/a2ui | protocol/oauth | security\n\n' +
    'Findings:\n' + JSON.stringify(toCodeify, null, 2),
    { schema: SDK_SCAN_SCHEMA, label: 'sdk:scan', phase: 'Codify' }
  )

  if (sdkScan && sdkScan.sdkCandidates.length > 0) {
    sdkCandidatesCount = sdkScan.sdkCandidates.length
    const candidateLines = sdkScan.sdkCandidates.map(function(c, i) {
      return '## Candidate ' + (i + 1) + ': ' + c.description + '\n' +
             '- Severity: ' + c.severity + '\n' +
             '- Component: ' + c.component + '\n' +
             '- File: ' + (c.file || 'n/a') + '\n' +
             '- Rationale: ' + c.rationale
    }).join('\n\n')

    await agent(
      'Write workspace/sdk-candidates.md with exactly this content:\n\n' +
      '# SDK issue candidates — ' + wave.waveId + ' (' + TODAY + ')\n\n' +
      'Run `/sdk-issue-scan` to review and file as GitHub issues on `wailuen/a2a-sdk`.\n\n' +
      candidateLines,
      { label: 'sdk:candidates', phase: 'Codify' }
    )
    log('SDK candidates: ' + sdkCandidatesCount + ' finding(s) → workspace/sdk-candidates.md')
    log('Run /sdk-issue-scan to file them')
  } else {
    log('SDK issue scan: no SDK-level findings in this wave')
  }

  await parallel(toCodeify.map(function(f, i) {
    return function() {
      const lrnNum = lrnBase + i
      const lrnId  = 'LRN-' + String(lrnNum).padStart(3, '0')
      return agent(
        'Write a learning file. Do NOT touch workspace/learning/README.md yet.\n\n' +
        'Assigned ID: ' + lrnId + '\n' +
        'File path: workspace/learning/' + lrnId + '-<slug>.md\n' +
        'Slug: 2-4 kebab-case words for the bug CLASS (not this instance).\n\n' +
        'Finding:\n' + JSON.stringify(f, null, 2) + '\n\n' +
        'Format (frontmatter mandatory):\n' +
        '---\n' +
        'id: ' + lrnId + '\n' +
        'title: <short title>\n' +
        'category: security | protocol | sdk | testing | ops\n' +
        'severity: ' + f.severity + '\n' +
        'source: ' + (f.file === 'protocol-surface' ? 'protocol-audit' : 'redteam') + '\n' +
        'date: ' + TODAY + '\n' +
        '---\n\n' +
        '## What happened\n<2-3 sentences>\n\n' +
        '## Root cause\n<1-2 sentences>\n\n' +
        '## Check\n<specific grep or test to verify>\n\n' +
        '## Prevention\n<actionable planner constraint>\n\n' +
        'Keep under 1KB.',
        { label: 'codify:' + lrnId, phase: 'Codify', agentType: 'codify' }
      )
    }
  }))

  await agent(
    'Scan workspace/learning/ for every LRN-NNN-*.md file. Read each frontmatter.\n' +
    'Rewrite workspace/learning/README.md:\n\n' +
    '# Learning index\n\n' +
    'Entries ordered by LRN number.\n\n' +
    '| LRN | Description | File |\n' +
    '|-----|-------------|------|\n' +
    '| LRN-NNN | <title> | [LRN-NNN](LRN-NNN-slug.md) |\n\n' +
    'One row per file, ordered by number.',
    { label: 'codify:readme', phase: 'Codify', agentType: 'codify' }
  )
}

if (registryCandidates.length > 0) {
  log('Registering ' + registryCandidates.length + ' new component candidate(s)')
  await agent(
    'Register new reusable components for wave ' + wave.waveId + '.\n\n' +
    'Read workspace/components/README.md to find highest C-NNN ID.\n\n' +
    'New candidates:\n' + JSON.stringify(registryCandidates, null, 2) + '\n\n' +
    'For each: assign next C-NNN, determine status (present/planned), append row to README.\n' +
    'Do NOT modify existing rows. Report: IDs assigned.',
    { label: 'registry:register', phase: 'Codify' }
  )
}

// ─── phase 7: archive ─────────────────────────────────────────────────────────
phase('Archive')

const preArchiveGate = await agent(
  'Run: .venv/bin/pytest -q tests/\n' +
  'Report: exitCode (0=pass, non-zero=fail), passCount, failCount, failures. Return all fields.',
  { schema: GATE_SCHEMA, label: 'gate:pre-archive', phase: 'Archive' }
)
if (!preArchiveGate) {
  // RT-001: gate agent failed — archive must not proceed on unknown state.
  testsRed = true
  protocolBlocked = true
  testsBlockedArchive = true
  log('WARNING: pre-archive gate agent failed (null response) — archive BLOCKED (gate agent failed; unknown test state)')
  log('Re-run /wave ' + wave.waveId + ' to retry the pre-archive gate.')
} else if (preArchiveGate.exitCode !== 0) {
  // RT-003: track the cause separately so the archive-skip message is accurate.
  testsRed = true
  protocolBlocked = true
  testsBlockedArchive = true
  log('Suite is RED (' + preArchiveGate.failCount + ' failing) — archive BLOCKED.')
  log('Fix the failing tests and re-run /wave ' + wave.waveId)
}

// GH-84: pre-archive commit check — all scope files (Creates: ∪ Modifies:) plus any
// harness deliverable directories must be committed before archive. A wave that archives
// with deliverables only in the working tree will silently lose them on `git checkout`.
if (!protocolBlocked) {
  const archiveIntent = await agent(
    'Run `git status --short` and parse the output.\n\n' +
    'Scope paths for this wave (Creates: ∪ Modifies:):\n' + wave.allScope.join('\n') + '\n\n' +
    'Steps:\n' +
    '1. Run: git status --short\n' +
    '2. Collect ALL paths that appear in the output (dirty or untracked).\n' +
    '3. Cross-reference dirty paths against the scope list above for offendingPaths.\n' +
    '   A dirty path is an offender when:\n' +
    '   a. It exactly matches a scope entry, OR\n' +
    '   b. It starts with a scope entry (the scope entry is a directory prefix), OR\n' +
    '   c. A scope entry starts with the dirty path (dirty parent directory).\n' +
    '4. Separately, collect any dirty/untracked paths whose relative path starts with\n' +
    '   tests/, workspace/learning/, workspace/scenarios/results/, or workspace/prd/\n' +
    '   — put these in offendingHarnessPaths even if they do not appear in the scope list.\n' +
    '5. Return all four fields.\n\n' +
    'If the working tree is completely clean, gitStatusOutput is empty string,\n' +
    'dirtyPaths is [], offendingPaths is [], offendingHarnessPaths is [].',
    { schema: ARCHIVE_INTENT_SCHEMA, label: 'gate:archive-commit', phase: 'Archive' }
  )

  if (!archiveIntent) {
    protocolBlocked = true
    log('WARNING: archive-commit gate agent returned null — archive BLOCKED (unknown commit state). Re-run /wave ' + wave.waveId)
    // WC-001 mirror: write a durable deferred note so the operator can inspect why archive
    // was blocked even after the console output scrolls away.
    await agent(
      'Write workspace/todos/deferred/' + wave.waveId + '-archive-commit-null.md\n\n' +
      'Include: wave ID (' + wave.waveId + '), date (' + TODAY + '),\n' +
      'reason: archive-commit gate agent returned null (unknown working tree state).\n' +
      'Instruction: "Re-run /wave ' + wave.waveId + ' to retry the archive-commit gate."',
      { label: 'defer:archive-commit-null', phase: 'Archive' }
    )
  } else if ((archiveIntent.offendingPaths && archiveIntent.offendingPaths.length > 0) ||
             (archiveIntent.offendingHarnessPaths && archiveIntent.offendingHarnessPaths.length > 0)) {
    protocolBlocked = true
    if (archiveIntent.offendingPaths && archiveIntent.offendingPaths.length > 0) {
      log('Archive BLOCKED — ' + archiveIntent.offendingPaths.length + ' scope file(s) are uncommitted:')
      archiveIntent.offendingPaths.forEach(function(p) { log('  [uncommitted] ' + p) })
    }
    if (archiveIntent.offendingHarnessPaths && archiveIntent.offendingHarnessPaths.length > 0) {
      log('Archive BLOCKED — ' + archiveIntent.offendingHarnessPaths.length + ' harness deliverable(s) are uncommitted:')
      archiveIntent.offendingHarnessPaths.forEach(function(p) { log('  [uncommitted] ' + p) })
    }
    log('Commit or stage the files above, then re-run /wave ' + wave.waveId)
  } else {
    log('Commit check passed — all scope files and harness deliverables are committed')
  }
}

if (protocolBlocked) {
  // RT-003: use the actual block cause in the message — misdirected remediation wastes developer time.
  if (testsBlockedArchive) {
    const failCount = (preArchiveGate && preArchiveGate.failCount != null) ? preArchiveGate.failCount : '?'
    if (!preArchiveGate) {
      log('Archive SKIPPED — pre-archive gate agent failed (null response). Re-run /wave ' + wave.waveId + ' to retry.')
    } else {
      log('Archive BLOCKED — test suite RED (' + failCount + ' failing). Fix failing tests and re-run /wave ' + wave.waveId + '.')
    }
  } else {
    log('Archive SKIPPED — wave ' + wave.waveId + ' blocked by critical protocol findings')
    log('Fix protocol issues, run /agent-verify, then re-run /wave ' + wave.waveId)
  }
} else {
  await agent(
    'Archive wave ' + wave.waveId + '. Perform in order:\n\n' +
    '1. Move `' + WAVE_FILE + '` → `workspace/todos/completed/` (same filename).\n\n' +
    '2. In `workspace/todos/plan.md`, find the row for ' + wave.waveId + ':\n' +
    '   - If a row already exists: change [ ] to [x] and append ✅ ' + TODAY + ' after the wave title.\n' +
    '   - If NO row exists (GH-issue waves are not pre-seeded): append a new row to the Wave summary table:\n' +
    '     `| ' + wave.waveId.toUpperCase() + ' [x] ✅ ' + TODAY + ' | ' + WAVE_FILE.replace('workspace/todos/', '') + ' | G | — | — |`\n' +
    '     Adjust the Slices column if you can determine the count from the file.\n\n' +
    '3. For each path in the scope list, find the matching FR in workspace/prd/ if any.\n' +
    '   If Implementation: says [pending], replace with the real path:symbol.\n' +
    '   Scope paths (Creates: ∪ Modifies:):\n' + wave.allScope.join('\n') + '\n\n' +
    'Report: file moved, plan.md updated (row updated or appended), FR fields updated.',
    { label: 'archive', phase: 'Archive' }
  )

  log('Wave ' + wave.waveId + ' archived — ' + toCodeify.length + ' LRN(s) captured')
}

return {
  waveId:             wave.waveId,
  totalTodos:         totalTodos,
  lrnsCaptured:       toCodeify.length,
  cNnnRegistered:     registryCandidates.length,
  sdkCandidates:      sdkCandidatesCount,
  groupsExecuted:     wave.groups.length,
  phaseRedteamRounds: pRound,
  exhausted:          pRound >= 8,
  protocolBlocked:    protocolBlocked,
  testsRed:           testsRed,
}
