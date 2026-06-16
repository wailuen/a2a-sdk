export const meta = {
  name: 'wave-cycle',
  description: 'Execute one wave: todos plan redteam (SI annotations + registry reuse) → fan-out implement per group → unit zero-tolerance redteam (debug after >3 failed rounds (r4+) and on stall) → phase zero-tolerance redteam (debug after >3 failed rounds (r4+) and on stall) → protocol audit → codify LRNs + register new C-NNN components → archive',
  phases: [
    { title: 'Parse',          detail: 'Read wave file; extract groups, creates paths, LRN baseline' },
    { title: 'Todos Redteam',  detail: 'Redteam the wave plan: SI risk annotation, registry reuse (Reuses: C-NNN), new component candidate flagging — annotated wave file written back before implement' },
    { title: 'Implement',      detail: 'Fan out todos per group in dependency order; smoke test each' },
    { title: 'Unit Redteam',   detail: 'Per-group zero-tolerance fix loop (max 5 rounds/group; debug fires after >3 failed rounds (r4+) and on stall)' },
    { title: 'Phase Redteam',  detail: 'Full-wave zero-tolerance fix loop (max 8 rounds; debug fires after >3 failed rounds (r4+) and on stall)' },
    { title: 'Protocol Audit', detail: 'A2A/MCP/AG-UI/A2UI conformance — parallel advisors + seam check (protocol-surface waves only)' },
    { title: 'Codify',         detail: 'SDK issue scan (sequential) → parallel LRN capture for critical/high findings → README index update → sequential C-NNN registration for new component candidates' },
    { title: 'Archive',        detail: 'Move wave file to completed/, update plan.md, backfill FR Implementation: fields' },
  ],
}

// ─── args ─────────────────────────────────────────────────────────────────────
// args.waveFile : absolute path to the active wave file
// args.today    : ISO date string for plan.md timestamp (e.g. "2026-06-12")
const WAVE_FILE = args.waveFile
const TODAY     = args.today || '(see context date)'

// ─── protocol surface paths (trigger the Protocol Audit phase) ─────────────────
const A2A_SURFACE  = ['src/routes/a2a', 'src/routes/agent_card', 'src/models/a2a']
const MCP_SURFACE  = ['src/routes/mcp', 'src/routes/oauth']
const AGUI_SURFACE = ['src/routes/ag_ui']
const A2UI_SURFACE = ['src/a2ui/', 'src/models/content_types']

// ─── schemas ──────────────────────────────────────────────────────────────────

const WAVE_SCHEMA = {
  type: 'object',
  required: ['waveId', 'allCreates', 'groups', 'groupDeps', 'lrnNext'],
  additionalProperties: false,
  properties: {
    waveId:     { type: 'string' },
    allCreates: { type: 'array', items: { type: 'string' } },
    lrnNext:    { type: 'integer' },
    groupDeps: {
      type: 'object',
      description: 'Maps group label to the labels of OTHER groups it depends on (empty array = no external deps)',
      additionalProperties: { type: 'array', items: { type: 'string' } },
    },
    groups: {
      type: 'array',
      items: {
        type: 'object',
        required: ['label', 'creates', 'todos'],
        additionalProperties: false,
        properties: {
          label:   { type: 'string' },
          creates: { type: 'array', items: { type: 'string' } },
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

// SDK issue scan schema — classifies findings as SDK-level vs agent-domain
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

// GH-19: pytest gate schema — exit code + failure list consumed to block fix loops
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

// ─── helpers ──────────────────────────────────────────────────────────────────

// Stall detection uses description (not id) because agents re-derive ids each round.
function sigs(findings) {
  return new Set(findings.map(function(f) { return f.file + ':' + f.description }))
}

function sigsEqual(a, b) {
  if (a.size !== b.size) return false
  for (const k of a) { if (!b.has(k)) return false }
  return true
}

// ─── state ────────────────────────────────────────────────────────────────────
let registryCandidates = []   // new C-NNN candidates from Todos Redteam → registered in Codify

// ─── phase 0: parse wave file ─────────────────────────────────────────────────
phase('Parse')

const wave = await agent(
  'Read the wave file at: ' + WAVE_FILE + '\n\n' +
  'Also read workspace/learning/README.md to find the highest LRN number ' +
  '(e.g. LRN-023 → lrnNext = 24; if none, lrnNext = 1).\n\n' +
  'Extract:\n' +
  '- waveId: the w[NNN] identifier from the filename\n' +
  '- allCreates: every "Creates:" path listed across all todos in this wave\n' +
  '- lrnNext: highest existing LRN number + 1\n' +
  '- groups: execution groups (Depends: respected).\n' +
  '  Todos without ‖ group: get label "ungrouped-N" (N = position).\n' +
  '  Same ‖ group: label → same group entry.\n' +
  '  Do NOT impose a sequential ordering — let groupDeps express ordering instead.\n' +
  '- groupDeps: for each group label, list the labels of OTHER groups whose todos\n' +
  '  appear in any `Depends:` field of this group\'s todos.\n' +
  '  A group with no external Depends: references maps to [].\n' +
  '  Todos that Depends: on another todo in the SAME group do not add a dep entry.\n' +
  '  Format: {"A": [], "B": ["A"], ...}\n\n' +
  'Return structured data.',
  { schema: WAVE_SCHEMA, label: 'parse', phase: 'Parse' }
)

if (!wave) {
  log('ERROR: could not parse wave file at ' + WAVE_FILE)
  return { error: 'parse-failed' }
}

log('Wave ' + wave.waveId + ': ' + wave.groups.length + ' group(s), ' +
    wave.allCreates.length + ' creates path(s), lrnNext=' + wave.lrnNext)

const lrnBase          = wave.lrnNext
const allHighFindings  = []   // accumulates critical/high for codify phase
let   protocolBlocked  = false
let   testsRed         = false
let   totalTodos       = 0
let   sdkCandidatesCount = 0   // set by sdk:scan in Codify phase

// ─── phase 1: todos redteam ───────────────────────────────────────────────────
phase('Todos Redteam')

const planRt = await agent(
  'Review the todo plan for wave ' + wave.waveId + ' BEFORE implementation starts.\n\n' +
  'Wave file: ' + WAVE_FILE + '\n' +
  'Also read:\n' +
  '  - workspace/components/README.md  (C-NNN registry)\n' +
  '  - workspace/learning/README.md    (past learnings + Prevention clauses)\n' +
  '  - .claude/reference/sdk-security-invariants.md  (SI-1…SI-7)\n\n' +
  'Check ONLY these four things (do not re-audit cross-wave ordering):\n' +
  '1. REGISTRY REUSE — does a C-NNN component already cover this todo\'s capability?\n' +
  '   If yes, add to reuseAnnotations. Implementers will use the annotation to\n' +
  '   reuse the component rather than rebuild it.\n' +
  '2. SI RISK — does this todo\'s Creates: path touch SI-1..SI-7 territory?\n' +
  '   If yes and SI: field is absent, add to siAnnotations.\n' +
  '3. VERTICAL SLICE — is this todo a horizontal layer instead of an end-to-end\n' +
  '   deliverable? Add to sliceIssues only if genuinely non-vertical.\n' +
  '4. NEW COMPONENT CANDIDATES — would any planned code be reusable across\n' +
  '   multiple agents or waves? Add name/location/description to newCandidates.\n\n' +
  'If the plan is already clean, issuesFound=false and all arrays empty.\n' +
  'Do NOT re-derive issues the plan-level redteam already confirmed.\n\n' +
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
        '- Match todo by its backtick-wrapped ID on the checkbox line (e.g. `- [ ] `P1-01` description`)\n' +
        '- Append annotation lines immediately after the last indented field of that todo block,\n' +
        '  before the next `- [ ]` line or section header\n' +
        '- Preserve all whitespace and structure\n\n' +
        'Report: which todos were annotated.',
        { label: 'rt:todos:annotate', phase: 'Todos Redteam' }
      )
    }
  }
} else {
  log('Todos Redteam agent returned null — proceeding to implementation')
}

// ─── phase 2: implement ───────────────────────────────────────────────────────
phase('Implement')

// Tier-based parallel execution: each tier contains groups whose external deps
// are all satisfied by previously-completed tiers. Groups within a tier run in
// parallel (no file conflict, since the planner groups conflicting todos together).
const completedGroups = new Set()
const remainingGroups = wave.groups.slice()

while (remainingGroups.length > 0) {
  // Collect all groups ready to run (all external deps complete)
  const readyGroups = remainingGroups.filter(function(g) {
    const deps = (wave.groupDeps && wave.groupDeps[g.label]) || []
    return deps.every(function(dep) { return completedGroups.has(dep) })
  })

  if (readyGroups.length === 0) {
    // Circular or unresolvable dep — fall back: run first remaining group
    log('WARNING: unresolvable group dependency; falling back to sequential for group ' + remainingGroups[0].label)
    readyGroups.push(remainingGroups[0])
  }

  // Remove from remaining
  for (const rg of readyGroups) {
    const idx = remainingGroups.findIndex(function(g) { return g.label === rg.label })
    if (idx !== -1) remainingGroups.splice(idx, 1)
  }

  const tierLabel = readyGroups.map(function(g) { return g.label }).join(', ')
  totalTodos += readyGroups.reduce(function(n, g) { return n + g.todos.length }, 0)

  if (readyGroups.length > 1) {
    log('Implementing ' + readyGroups.length + ' groups in parallel: ' + tierLabel)
  }

  // Build per-group implement thunks
  function makeGroupThunk(group) {
    return function() {
      log('Implementing group ' + group.label + ' (' + group.todos.length + ' todo(s))')
      if (group.todos.length === 1) {
        const todo = group.todos[0]
        return agent(
          'Implement this todo. Read CLAUDE.md and workspace/components/README.md first.\n\n' +
          'CLAUDE.md security invariants (SI-1…SI-7) apply — enforce them in your output:\n' +
          'SI-1: no raw httpx in src/tools/; SI-2: no secrets in error messages;\n' +
          'SI-3: url_segment()/safe_id() for URL path vars in adapters;\n' +
          'SI-4: self.credential() only for creds; SI-5: auth on all endpoints;\n' +
          'SI-6: vendor keys in credential store only; SI-7: non-empty allowed_hosts.\n\n' +
          'Test-first discipline: for correctness-bearing code (tool logic, validation,\n' +
          'serialisation), write the failing test FIRST (confirm RED), then the code\n' +
          '(confirm GREEN), then refactor. The todo is not done until the test was RED.\n\n' +
          'Todo:\n' + todo.body + '\n\n' +
          'You MAY run scoped tests (`python -m pytest -q tests/test_<specific>.py`) to confirm\n' +
          'RED→GREEN for your own files. Do NOT run the full test suite — a centralized gate\n' +
          'runs after all groups finish and will catch suite-wide regressions.\n' +
          'Report: files created/modified, RED→GREEN confirmation, any blockers.',
          { label: 'impl:' + todo.id, phase: 'Implement', agentType: 'python-implementer' }
        )
      } else {
        return parallel(group.todos.map(function(todo) {
          return function() {
            return agent(
              'Implement this todo. Read CLAUDE.md and workspace/components/README.md first.\n\n' +
              'CLAUDE.md security invariants (SI-1…SI-7) apply — enforce them in your output:\n' +
              'SI-1: no raw httpx in src/tools/; SI-2: no secrets in error messages;\n' +
              'SI-3: url_segment()/safe_id() for URL path vars in adapters;\n' +
              'SI-4: self.credential() only for creds; SI-5: auth on all endpoints;\n' +
              'SI-6: vendor keys in credential store only; SI-7: non-empty allowed_hosts.\n\n' +
              'Test-first for correctness-bearing code (RED then GREEN then refactor).\n\n' +
              'Todo:\n' + todo.body + '\n\n' +
              'You MAY run scoped tests (`python -m pytest -q tests/test_<specific>.py`) to confirm\n' +
              'RED→GREEN for your own files. Do NOT run the full test suite — a centralized gate\n' +
              'runs after all groups finish. Report: files created/modified, RED→GREEN confirmation.',
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

// ─── phase 3: unit redteam (per group, zero-tolerance) ───────────────────────
phase('Unit Redteam')

for (const group of wave.groups) {
  log('Unit redteam — group ' + group.label)
  let uRound       = 0
  let prevSigs     = new Set()

  while (true) {
    uRound++

    const rt = await agent(
      'Adversarial review of the files created/modified by group ' + group.label + '.\n\n' +
      'Scope (Creates: paths for this group):\n' + group.creates.join('\n') + '\n\n' +
      'Also check their transitive callers and importers.\n\n' +
      'Run all 8 dimensions from agents/core/redteam.md. Include the SDK Security\n' +
      'Invariants (SI-1…SI-7) in the security dimension — fail closed.\n\n' +
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

    // Deferred-exit check before debug — avoids wasting a debug agent call that's immediately abandoned.
    if (uRound >= 5) {
      log('Round budget exhausted for group ' + group.label + ' — deferring')
      await agent(
        'Write workspace/todos/deferred/' + wave.waveId + '-group-' + group.label + '-budget-exhausted.md\n\n' +
        'Include: wave ID (' + wave.waveId + '), group (' + group.label + '), date (' + TODAY + '),\n' +
        'round count (' + uRound + '), and the final findings:\n' +
        JSON.stringify(rt.findings, null, 2) + '\n\n' +
        'Instruction in the file: "Fix remaining findings, then re-run /wave ' + wave.waveId + '".',
        { label: 'defer:unit:' + group.label, phase: 'Unit Redteam' }
      )
      break
    }

    // Debug fires at rounds 3–4 (unconditionally) and whenever stalled; round 5 exits above.
    if (uRound > 3 || stalled) {
      log((stalled ? 'Stall detected — ' : 'Round 4+ — ') + 'escalating to debug agent')
      await agent(
        'Fix-loop requires fresh-lens analysis' + (stalled ? ' (stalled: same findings across 2 rounds)' : ' (round ' + uRound + ')') + '.\n\n' +
        'Prior findings:\n' + JSON.stringify(rt.findings, null, 2) + '\n\n' +
        'Scope:\n' + group.creates.join('\n') + '\n\n' +
        'Read code cold. Diagnose root cause. Fix at the root.',
        { label: 'debug:unit:' + group.label + ':r' + uRound, phase: 'Unit Redteam', agentType: 'debug' }
      )
    }
    prevSigs = curSigs

    // Bucket by file and dispatch fix specialists in parallel.
    // Codify accumulates in allHighFindings for the dedicated phase 6 LRN pass.
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
          'Enforce SDK SI-1…SI-7 in your fix. Run pytest -q after.',
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

    // GH-19: consume gate result — red suite blocks loop continuation
    const unitGate = await agent(
      'Run: python -m pytest -q\n' +
      'Report: exitCode (0=pass, non-zero=fail), passCount, failCount, and failures (list of\n' +
      '"test_file.py::test_name: reason" strings for each failing test). Return all fields.',
      { schema: GATE_SCHEMA, label: 'gate:unit:' + group.label + ':r' + uRound, phase: 'Unit Redteam' }
    )
    if (unitGate && unitGate.exitCode !== 0) {
      testsRed = true
      log('Gate RED (' + unitGate.failCount + ' failing) — dispatching test-fix agent')
      await agent(
        'Fix the failing tests below. Read the test file and the source it covers.\n' +
        'Failing tests:\n' + unitGate.failures.join('\n') + '\n\n' +
        'Run `python -m pytest -q <failing-test-file>` to confirm GREEN before finishing.',
        { label: 'fix:tests:unit:' + group.label + ':r' + uRound, phase: 'Unit Redteam' }
      )
    }
  }
}

// ─── phase 4: phase redteam (whole wave, zero-tolerance) ─────────────────────
phase('Phase Redteam')

let pRound   = 0
let prevSigs = new Set()

while (true) {
  pRound++

  const rt = await agent(
    'Adversarial review of the full wave ' + wave.waveId + '.\n\n' +
    'Scope (all Creates: paths across every group):\n' +
    wave.allCreates.join('\n') + '\n\n' +
    'Also check transitive callers and importers. Re-expand scope every round.\n\n' +
    'Run all 8 dimensions. SDK Security Invariants (SI-1…SI-7) fail closed.\n\n' +
    'Return structured findings.',
    { schema: RT_SCHEMA, label: 'rt:phase:r' + pRound, phase: 'Phase Redteam',
      agentType: 'redteam' }
  )

  if (!rt || rt.findingsCount === 0) {
    log('Phase redteam clean at round ' + pRound)
    break
  }

  log('Phase redteam round ' + pRound + ': ' + rt.findingsCount + ' finding(s)')

  const curSigs = sigs(rt.findings)
  const pStalled = pRound > 1 && sigsEqual(curSigs, prevSigs)

  // Budget-exit check before debug — avoids wasting a debug agent call that's immediately abandoned.
  if (pRound >= 8) {
    log('Phase round budget exhausted — continuing to Protocol Audit')
    break
  }

  // Debug fires at rounds 3–7 (unconditionally) and whenever stalled; round 8 exits above.
  if (pRound > 3 || pStalled) {
    log((pStalled ? 'Stall detected — ' : 'Round 4+ — ') + 'escalating to debug agent')
    await agent(
      'Phase fix-loop requires fresh-lens analysis' + (pStalled ? ' (stalled)' : ' (round ' + pRound + ')') + '.\n\n' +
      'Findings:\n' + JSON.stringify(rt.findings, null, 2) + '\n\n' +
      'Scope:\n' + wave.allCreates.join('\n') + '\n\n' +
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
        'Enforce SI-1…SI-7. Run pytest -q after.',
        { label: 'fix:phase:r' + pRound + ':' + file.replace(/\//g, '-'),
          phase: 'Phase Redteam', agentType: 'python-implementer' }
      )
    }
  })

  const highFindings = rt.findings.filter(function(f) {
    return (f.severity === 'critical' || f.severity === 'high') && f.codify
  })
  allHighFindings.push.apply(allHighFindings, highFindings)
  await parallel(fixTasks)

  // GH-19: consume gate result — red suite blocks loop continuation
  const phaseGate = await agent(
    'Run: python -m pytest -q\n' +
    'Report: exitCode (0=pass, non-zero=fail), passCount, failCount, and failures (list of\n' +
    '"test_file.py::test_name: reason" strings for each failing test). Return all fields.',
    { schema: GATE_SCHEMA, label: 'gate:phase:r' + pRound, phase: 'Phase Redteam' }
  )
  if (phaseGate && phaseGate.exitCode !== 0) {
    testsRed = true
    log('Gate RED (' + phaseGate.failCount + ' failing) — dispatching test-fix agent')
    await agent(
      'Fix the failing tests below. Read the test file and the source it covers.\n' +
      'Failing tests:\n' + phaseGate.failures.join('\n') + '\n\n' +
      'Run `python -m pytest -q <failing-test-file>` to confirm GREEN before finishing.',
      { label: 'fix:tests:phase:r' + pRound, phase: 'Phase Redteam' }
    )
  }
}

// ─── phase 5: protocol audit ──────────────────────────────────────────────────
phase('Protocol Audit')

const runA2A  = wave.allCreates.some(function(p) {
  return A2A_SURFACE.some(function(pp) { return p.indexOf(pp) !== -1 })
})
const runMCP  = wave.allCreates.some(function(p) {
  return MCP_SURFACE.some(function(pp) { return p.indexOf(pp) !== -1 })
})
const runAGUI = wave.allCreates.some(function(p) {
  return AGUI_SURFACE.some(function(pp) { return p.indexOf(pp) !== -1 })
})
const runA2UI = wave.allCreates.some(function(p) {
  return A2UI_SURFACE.some(function(pp) { return p.indexOf(pp) !== -1 })
})
const runProtocol = runA2A || runMCP || runAGUI || runA2UI

if (!runProtocol) {
  log('Protocol audit skipped — no protocol surfaces in creates list')
} else {
  log('Protocol audit triggered (A2A=' + runA2A + ' MCP=' + runMCP + ' AG-UI=' + runAGUI + ' A2UI=' + runA2UI + ')')
  // AD-001: advisor agents are external (check kit). If the kit is absent they fall back to
  // the default agent and results will be incomplete — log what we expect so the user can verify.
  log('Protocol audit: requires a2a-advisor / mcp-advisor / ag-ui-advisor / a2ui-advisor from the check kit. ' +
      'If the kit is absent, advisor legs return partial or empty results — NOT a green pass.')

  const advisorTasks = []

  if (runA2A) {
    advisorTasks.push(function() {
      return agent(
        'A2A v0.3.0 conformance audit.\n\n' +
        'Files to audit:\n' +
        wave.allCreates.filter(function(p) {
          return A2A_SURFACE.some(function(pp) { return p.indexOf(pp) !== -1 })
        }).join('\n') + '\n\n' +
        'Check: agent card shape, task/message/part/artifact shapes, streaming,\n' +
        'error codes (-32001 through -32007 → correct HTTP status), auth.\n\n' +
        'Return structured findings. Set protocol="A2A" per finding.',
        { schema: PROTO_SCHEMA, agentType: 'a2a-advisor', label: 'proto:a2a', phase: 'Protocol Audit' }
      )
    })
  }

  if (runMCP) {
    advisorTasks.push(function() {
      return agent(
        'MCP conformance audit.\n\n' +
        'Files to audit:\n' +
        wave.allCreates.filter(function(p) {
          return MCP_SURFACE.some(function(pp) { return p.indexOf(pp) !== -1 })
        }).join('\n') + '\n\n' +
        'Check: Streamable-HTTP transport, OAuth 2.1 discovery (/.well-known/oauth-authorization-server),\n' +
        'PKCE (S256, code_challenge_method), initialize request/response echo (protocolVersion,\n' +
        'serverInfo, capabilities), tools/list shape (name, description, inputSchema),\n' +
        'token endpoint CORS, and auth error codes.\n\n' +
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
        wave.allCreates.filter(function(p) {
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
        wave.allCreates.filter(function(p) {
          return A2UI_SURFACE.some(function(pp) { return p.indexOf(pp) !== -1 })
        }).join('\n') + '\n\n' +
        'Check: createSurface/updateComponents/updateDataModel/deleteSurface shapes,\n' +
        'Core 6 + Extended 8 Standard Profile types only (14 FROZEN total; 4 RESERVED names are never emitted), JSON-Pointer binding,\n' +
        'A2A DataPart delivery, translator.py message types, field contracts.\n\n' +
        'Return structured findings. Set protocol="A2UI" per finding.',
        { schema: PROTO_SCHEMA, agentType: 'a2ui-advisor', label: 'proto:a2ui', phase: 'Protocol Audit' }
      )
    })
  }

  // Seam check: no specialist agentType — it reads multiple protocol surfaces together,
  // so no single advisor owns it. Uses the default agent with full cross-surface context.
  advisorTasks.push(function() {
    return agent(
      'Cross-protocol seam audit — consistency ACROSS A2A, MCP, AG-UI, A2UI surfaces.\n\n' +
      'Read: src/routes/agent_card.py, src/routes/a2a.py, src/routes/mcp.py,\n' +
      'src/routes/oauth.py, and any AG-UI/A2UI route files in the creates list.\n\n' +
      'Wave creates paths:\n' + wave.allCreates.join('\n') + '\n\n' +
      'Check:\n' +
      '- Agent card skills array contains one entry per @tool in the ToolRegistry (no tool advertised in the card is absent from the registry).\n' +
      '- src/skills/*.md files are reachable via the load_skill tool (skills_dir is wired in the Agent constructor); these are separate from the card\'s skills[] and no 1:1 count match is required.\n' +
      '- Agent card streaming flag matches actual SSE implementation.\n' +
      '- Auth mode enforced uniformly: no surface accepts a token type another rejects.\n' +
      '- Version strings identical across agent card, MCP server info, health endpoint.\n\n' +
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
      'Run pytest -q after fixing. Report files changed.',
      { label: 'proto:fix', phase: 'Protocol Audit', agentType: 'python-implementer' }
    )

    // GH-20: gate after protocol fix — domain regressions must be caught before recheck
    const protoFixGate = await agent(
      'Run: python -m pytest -q\n' +
      'Report: exitCode (0=pass, non-zero=fail), passCount, failCount, and failures (list of\n' +
      '"test_file.py::test_name: reason" strings for each failing test). Return all fields.',
      { schema: GATE_SCHEMA, label: 'gate:proto:fix', phase: 'Protocol Audit' }
    )
    if (protoFixGate && protoFixGate.exitCode !== 0) {
      testsRed = true
      log('Gate RED after proto:fix (' + protoFixGate.failCount + ' failing) — dispatching test-fix agent')
      await agent(
        'Fix the failing tests introduced by the protocol fix. Read the test file and source.\n' +
        'Failing tests:\n' + protoFixGate.failures.join('\n') + '\n\n' +
        'Run `python -m pytest -q <failing-test-file>` to confirm GREEN before finishing.',
        { label: 'fix:tests:proto:fix', phase: 'Protocol Audit' }
      )
    }

    // Recheck: same parallel advisor dispatch as the initial audit (including seam)
    const recheckTasks = []
    if (runA2A) {
      recheckTasks.push(function() {
        return agent(
          'A2A v0.3.0 re-audit after preceding fix. Check same surfaces.\n' +
          'Creates paths:\n' + wave.allCreates.join('\n') + '\n' +
          'Focus on previously-critical findings. Return structured findings.',
          { schema: PROTO_SCHEMA, agentType: 'a2a-advisor', label: 'proto:recheck:a2a', phase: 'Protocol Audit' }
        )
      })
    }
    if (runMCP) {
      recheckTasks.push(function() {
        return agent(
          'MCP re-audit after preceding fix. Check same surfaces.\n' +
          'Creates paths:\n' + wave.allCreates.join('\n') + '\n' +
          'Focus on previously-critical findings (Streamable-HTTP, OAuth 2.1, PKCE, initialize echo, tools/list). ' +
          'Return structured findings.',
          { schema: PROTO_SCHEMA, agentType: 'mcp-advisor', label: 'proto:recheck:mcp', phase: 'Protocol Audit' }
        )
      })
    }
    if (runAGUI) {
      recheckTasks.push(function() {
        return agent(
          'AG-UI re-audit after preceding fix.\n' +
          'Creates paths:\n' + wave.allCreates.join('\n') + '\n' +
          'Focus on previously-critical findings. Return structured findings.',
          { schema: PROTO_SCHEMA, agentType: 'ag-ui-advisor', label: 'proto:recheck:agui', phase: 'Protocol Audit' }
        )
      })
    }
    if (runA2UI) {
      recheckTasks.push(function() {
        return agent(
          'A2UI re-audit after preceding fix.\n' +
          'Creates paths:\n' + wave.allCreates.join('\n') + '\n' +
          'Focus on previously-critical findings. Return structured findings.',
          { schema: PROTO_SCHEMA, agentType: 'a2ui-advisor', label: 'proto:recheck:a2ui', phase: 'Protocol Audit' }
        )
      })
    }
    // Seam recheck: no specialist agentType for the same reason as the initial seam check.
    recheckTasks.push(function() {
      return agent(
        'Cross-protocol seam re-audit after preceding fix.\n' +
        'Creates paths:\n' + wave.allCreates.join('\n') + '\n' +
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
        '"Fix protocol findings, then run /agent-verify, then re-run /wave ' + wave.waveId + '".',
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

// ─── SDK issue scan (end of Codify) ──────────────────────────────────────────
// Classify critical/high findings as SDK-level vs agent-domain.
// SDK-level ones are written to workspace/sdk-candidates.md for /sdk-issue-scan.
if (toCodeify.length > 0) {
  const sdkScan = await agent(
    'Classify each finding as SDK-level or agent-domain.\n\n' +
    'SDK-LEVEL (include in output):\n' +
    '- Harness: wrong step in a SKILL.md, wrong agent instruction, wave-cycle.js logic error\n' +
    '- SDK internals: build_app(), Agent, ToolSet, SourceAdapter base class, credential store, loop\n' +
    '- Protocol surface: wrong HTTP status, missing handler, wrong shape in src/routes/\n' +
    '- Template scaffold: wrong pattern shown in template/, wrong SDK API in an example\n' +
    '- Security: an SI violation that the SDK itself causes (not domain code)\n\n' +
    'AGENT-DOMAIN (exclude):\n' +
    '- src/tools/, src/sources/, src/config.py, src/persona.py\n' +
    '- Agent-specific credential setup, domain test failures\n' +
    '- An SI violation in the agent\'s domain code (fix the code, not the SDK)\n\n' +
    'For each SDK-level finding, assign a component:\n' +
    'harness/skill | harness/workflow | harness/agent | harness/template |\n' +
    'sdk/build | sdk/loop | sdk/credentials | sdk/console |\n' +
    'protocol/a2a | protocol/mcp | protocol/ag-ui | protocol/a2ui | protocol/oauth | security\n\n' +
    'Findings to classify:\n' + JSON.stringify(toCodeify, null, 2),
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
      'Write the file workspace/sdk-candidates.md with exactly this content:\n\n' +
      '# SDK issue candidates — ' + wave.waveId + ' (' + TODAY + ')\n\n' +
      'These critical/high findings from wave ' + wave.waveId + ' are classified as\n' +
      'SDK-level. Run `/sdk-issue-scan` to review and file them as GitHub issues\n' +
      'on `wailuen/a2a-sdk`. One confirmation per filing — nothing is filed automatically.\n\n' +
      candidateLines,
      { label: 'sdk:candidates', phase: 'Codify' }
    )
    log('SDK issue candidates: ' + sdkScan.sdkCandidates.length + ' finding(s) written to workspace/sdk-candidates.md')
    log('Run /sdk-issue-scan to file them as GitHub issues on wailuen/a2a-sdk')
  } else {
    log('SDK issue scan: no SDK-level findings in this wave')
  }
}

if (toCodeify.length > 0) {
  await parallel(toCodeify.map(function(f, i) {
    return function() {
      const lrnNum = lrnBase + i
      const lrnId  = 'LRN-' + (lrnNum < 10 ? '00' : lrnNum < 100 ? '0' : '') + lrnNum
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
        '## What happened\n<2-3 sentences from the finding>\n\n' +
        '## Root cause\n<1-2 sentences>\n\n' +
        '## Check\n<specific grep or test to verify>\n\n' +
        '## Prevention\n<actionable planner constraint>\n\n' +
        'Keep the file under 1KB.',
        { label: 'codify:' + lrnId, phase: 'Codify', agentType: 'codify' }
      )
    }
  }))

  await agent(
    'Scan workspace/learning/ for every LRN-NNN-*.md file. Read each file\'s\n' +
    'frontmatter (id, title/description). Rewrite workspace/learning/README.md:\n\n' +
    '# Learning index\n\n' +
    'Entries ordered by LRN number. Planner and implementers apply Check/Prevention\n' +
    'clauses relevant to touched files.\n\n' +
    '| LRN | Description | File |\n' +
    '|-----|-------------|------|\n' +
    '| LRN-NNN | <title from frontmatter> | [LRN-NNN](LRN-NNN-slug.md) |\n\n' +
    'One row per file, ordered by number.',
    { label: 'codify:readme', phase: 'Codify', agentType: 'codify' }
  )
}

// Register new C-NNN components identified during Todos Redteam — sequential after parallel LRN agents
if (registryCandidates.length > 0) {
  log('Registering ' + registryCandidates.length + ' new component candidate(s) in workspace/components/README.md')
  await agent(
    'Register new reusable components discovered during wave ' + wave.waveId + '.\n\n' +
    'Read workspace/components/README.md to find the highest existing C-NNN ID.\n\n' +
    'New candidates:\n' + JSON.stringify(registryCandidates, null, 2) + '\n\n' +
    'For each candidate:\n' +
    '1. Assign the next C-NNN ID (increment from highest existing)\n' +
    '2. Determine status: if the location file already exists → "present"; else → "planned"\n' +
    '3. Append ONE new row to the README.md table:\n' +
    '   | C-NNN | <name> | <location> | <status> |\n\n' +
    'Do NOT modify existing rows. Append only. Report: IDs assigned and their locations.',
    { label: 'registry:register', phase: 'Codify' }
  )
}

// ─── phase 7: archive ─────────────────────────────────────────────────────────
phase('Archive')

// GH-22: pre-archive gate — suite must be green before marking wave complete
const preArchiveGate = await agent(
  'Run: python -m pytest -q\n' +
  'Report: exitCode (0=pass, non-zero=fail), passCount, failCount, and failures (list of\n' +
  '"test_file.py::test_name: reason" strings for each failing test). Return all fields.',
  { schema: GATE_SCHEMA, label: 'gate:pre-archive', phase: 'Archive' }
)
if (preArchiveGate && preArchiveGate.exitCode !== 0) {
  testsRed = true
  protocolBlocked = true  // reuse block-archive flag
  log('Suite is RED (' + preArchiveGate.failCount + ' failing) — archive BLOCKED.')
  log('Fix the failing tests and re-run /wave ' + wave.waveId)
}

if (protocolBlocked) {
  log('Archive SKIPPED — wave ' + wave.waveId + ' blocked by critical protocol findings')
  log('Fix protocol issues, run /agent-verify, then re-run /wave ' + wave.waveId)
} else {
  await agent(
    'Archive wave ' + wave.waveId + '. Perform in order:\n\n' +
    '1. Move `' + WAVE_FILE + '` → `workspace/todos/completed/` (same filename).\n\n' +
    '2. In `workspace/todos/plan.md`, find the row for ' + wave.waveId + ':\n' +
    '   - Change [ ] to [x]\n' +
    '   - Append ✅ ' + TODAY + ' after the wave title\n\n' +
    '3. For each path in the creates list, find the matching FR in workspace/prd/.\n' +
    '   If Implementation: says [pending], replace with the real src/path:symbol.\n' +
    '   Creates paths:\n' +
    wave.allCreates.join('\n') + '\n\n' +
    'Report: file moved, plan.md updated, FR fields updated.',
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
