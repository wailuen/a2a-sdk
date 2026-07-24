export const meta = {
  name: 'wave-cycle',
  description: 'Execute one wave: todos plan redteam (SI annotations + registry reuse) → fan-out implement per group → unit zero-tolerance redteam (debug fires unconditionally at round 4+ (uRound > 3) and at any round when stall is detected; round 5 exits via deferred note) → phase zero-tolerance redteam (debug fires unconditionally at round 4+ (pRound > 3) and at any round when stall is detected; round 8 exits) → protocol audit → codify LRNs + register new C-NNN components → archive',
  phases: [
    { title: 'Parse',          detail: 'Read wave file; extract groups, creates paths, LRN baseline' },
    { title: 'Todos Redteam',  detail: 'Redteam the wave plan: SI risk annotation, registry reuse (Reuses: C-NNN), new component candidate flagging — annotated wave file written back before implement' },
    { title: 'Implement',      detail: 'Fan out todos per group in dependency order; smoke test each' },
    { title: 'Unit Redteam',   detail: 'Per-group zero-tolerance fix loop (max 5 rounds/group; debug fires unconditionally at round 4+ (uRound > 3) and at any round when stall is detected (same findings as previous round); round 5 exits via deferred note)' },
    { title: 'Phase Redteam',  detail: 'Full-wave zero-tolerance fix loop (max 8 rounds; debug fires unconditionally at round 4+ (pRound > 3) and at any round when stall is detected (same findings as previous round); round 8 exits)' },
    { title: 'Protocol Audit', detail: 'A2A/MCP/AG-UI/A2UI conformance — parallel advisors + seam check (protocol-surface waves only)' },
    { title: 'Codify',         detail: 'SDK issue scan (sequential) → parallel LRN capture for critical/high findings → README index update → sequential C-NNN registration for new component candidates' },
    { title: 'Archive',        detail: 'Move wave file to completed/, update plan.md, backfill FR Implementation: fields' },
  ],
}

// ─── args ─────────────────────────────────────────────────────────────────────
// args.waveFile : absolute path to the active wave file
// args.today    : ISO date string for plan.md timestamp (e.g. "2026-06-12")
const WAVE_FILE = args.waveFile
const TODAY     = args.today || new Date().toISOString().slice(0, 10)

// ─── protocol surface paths (trigger the Protocol Audit phase) ─────────────────
// LRN-132/GH-123: src/routes/oauth is the OAuth discovery/token endpoints
// surface (PRM/authorize/token/register/revoke), not the store that backs
// require_identity. require_identity (defined in src/auth/middleware.py)
// delegates credential verification to OAuthTokenStore in
// src/auth/oauth_tokens.py via runtime.oauth.verify(). Both routes/oauth and
// middleware are shared surfaces every protected A2A, AG-UI, and MCP route
// depends on — not MCP-only. RT-001: middleware.py itself must also be a
// shared surface member — it is the file that actually DEFINES
// require_identity and is consumed directly via Depends() by all four route
// files. AUTH_SURFACE holds both paths and is folded into all three protocol
// arrays so a wave touching only oauth.py OR only middleware.py still
// dispatches a2a-advisor and ag-ui-advisor, not mcp-advisor alone.
// RT-001 (round-4 fresh-lens): AUTH_SURFACE now mirrors ALL FOUR members of
// sdk-wave.js's auth surface — routes/oauth, auth/middleware, and the two
// credential-verification backends auth/oauth_tokens (OAuthTokenStore.verify) and
// auth/api_keys (ApiKeyStore.verify) that require_identity delegates to. The prior
// 2-member list dropped oauth_tokens/api_keys on the rationale that they were "SDK
// internals with no equivalent file in a downstream agent's src/ tree", but that
// criterion never distinguished the KEPT members from the DROPPED ones: the standard
// agent src/ tree ships NEITHER src/auth/ NOR src/routes/ (only src/tools, src/sources,
// src/artifacts, src/skills), so src/routes/oauth and src/auth/middleware are exactly
// as absent downstream as oauth_tokens/api_keys. These path fragments are defensive —
// a custom agent that overrides ANY auth file (e.g. its credential store at
// src/auth/oauth_tokens.py) should dispatch the protocol advisors. Over-triggering the
// audit is fail-safe; under-triggering ships a security-relevant auth change unaudited,
// the exact GH-123/LRN-132 blind spot. Full parity with sdk-wave.js removes the
// asymmetry rather than defending it with a criterion that does not hold. (Each runner
// keeps its own path dialect: sdk-wave.js addresses agent_sdk/auth/*, wave-cycle.js
// src/auth/*.)
// RT-003 (round 5): both verify() backends (oauth_tokens.py, api_keys.py) `from .identity
// import Identity` and return an Identity — the object require_identity yields to every
// protected route's Depends(). By the same "trace transitive require_identity consumers"
// rule that added oauth_tokens/api_keys, src/auth/identity belongs in AUTH_SURFACE too — a
// wave touching only identity.py (e.g. a binding-key or kind-tag regression on the
// dataclass every audience check relies on) previously dispatched no protocol advisor at
// all. Mirrors sdk-wave.js's agent_sdk/auth/identity member.
const AUTH_SURFACE = ['src/routes/oauth', 'src/auth/middleware', 'src/auth/oauth_tokens', 'src/auth/api_keys', 'src/auth/identity']
const A2A_SURFACE  = ['src/routes/a2a', 'src/routes/agent_card', 'src/models/a2a'].concat(AUTH_SURFACE)
const MCP_SURFACE  = ['src/routes/mcp'].concat(AUTH_SURFACE)
const AGUI_SURFACE = ['src/routes/ag_ui'].concat(AUTH_SURFACE)
// RT-003 (low, this wave): A2UI_SURFACE deliberately does NOT fold in AUTH_SURFACE, unlike
// A2A_SURFACE/MCP_SURFACE/AGUI_SURFACE above. A2UI has no transport of its own — it is
// delivered exclusively as an A2A DataPart or an AG-UI CUSTOM event, so a wave touching only
// an AUTH_SURFACE file already sets runA2A/runAGUI (both fold in AUTH_SURFACE), dispatching
// a2a-advisor/ag-ui-advisor plus the unconditional seam leg below — the layer where A2UI's
// transport-level auth is actually enforced and audited. Folding AUTH_SURFACE in here too
// would dispatch a2ui-advisor on every auth-only wave for no added coverage: a2ui-advisor
// audits component/message-shape conformance, not authentication. Unlike AUTH_SURFACE's fold
// into the three transport arrays (a genuine under-triggering risk closed by GH-123/LRN-132),
// omitting it here is not an under-trigger — it is a documented exception, not a silent gap.
const A2UI_SURFACE = ['src/a2ui/', 'src/models/content_types']

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

// LRN-062 / RT-001: plan.md ledger row presence check — run after the archive step to verify
// the wave's row actually landed (GH-issue waves have no pre-seeded row, so this can't be
// assumed; w020 and w029 both archived successfully while silently skipping this append).
const PLAN_ROW_SCHEMA = {
  type: 'object',
  required: ['rowPresent', 'matchCount'],
  additionalProperties: false,
  properties: {
    rowPresent: { type: 'boolean' },
    matchCount: { type: 'number' },
  },
}

// GH-40 / GH-84: archive intent schema — git status check before archive
// The agent runs `git status --short`, parses the output into dirty paths,
// cross-references against wave.allScope (Creates: ∪ Modifies:), and returns any offending paths.
// GH-84 adds offendingHarnessPaths for dirty/untracked files under harness deliverable directories
// (tests/, workspace/learning/, workspace/scenarios/results/, workspace/prd/, .claude/workflows/,
// harness/workflows/). Post-archive w035 follow-up: the workflow-file dirs were added after a
// GH-118 fix (RT-003, below) landed in wave-cycle.js without either wave.allScope or this dir
// list watching wave-cycle.js/sdk-wave.js's own directories — an undeclared workflow-file edit
// could evade offendingPaths (undeclared) AND offendingHarnessPaths (dir unwatched) at once.
// RT-002 (round-7): template/.claude/workflows/ is the third byte-identical mirror (synced via
// test_workflow_sync.py). RT-001 (w036): that mirror lives inside a gitignored nested peer repo
// (template/), so it can NEVER show up in the top-level `git status --short` this gate runs in
// step 1 — watching it via the main-repo dirty-path list (step 4) was a dead guard. Step 4b
// separately runs `git -C template status --short` and folds any dirty .claude/workflows/ path
// from THAT output into offendingHarnessPaths (prefixed `template/`) — the only way this gate
// can see an uncommitted template mirror.
// GH-118 (LRN-119): the checks above only catch paths git already sees as dirty/untracked
// AND either in wave.allScope or under a harness dir — they never inspect import statements.
// A module extracted mid-wave (e.g. agent_sdk/common/origin.py in GH-110) that sits
// untracked, is imported by a declared file, but is itself outside both allScope and the
// harness dirs produces no offending entry and silently passes the gate — risking an
// ImportError at boot on every importing surface if archive stages only declared paths.
// offendingUndeclaredImports closes that gap: it holds resolved agent_sdk.* import targets
// of dirty/scope .py files that are themselves untracked and undeclared.
// RT-003: ported from sdk-wave.js — wave-cycle.js is the more widely-used wave runner and
// was left exposed to the LRN-119 failure class while sdk-wave.js alone carried the fix.
const ARCHIVE_INTENT_SCHEMA = {
  type: 'object',
  required: ['gitStatusOutput', 'dirtyPaths', 'offendingPaths', 'offendingHarnessPaths', 'offendingUndeclaredImports'],
  additionalProperties: false,
  properties: {
    gitStatusOutput:      { type: 'string', description: 'Raw stdout of git status --short' },
    dirtyPaths:           { type: 'array', items: { type: 'string' }, description: 'All paths reported dirty or untracked by git' },
    offendingPaths:       { type: 'array', items: { type: 'string' }, description: 'Dirty paths that overlap with wave.allScope (Creates: ∪ Modifies:)' },
    offendingHarnessPaths: { type: 'array', items: { type: 'string' }, description: 'Dirty/untracked paths under tests/, workspace/learning/, workspace/scenarios/results/, workspace/prd/, .claude/workflows/, or harness/workflows/ (step 4) — plus, per step 4b, any dirty .claude/workflows/ path from `git -C template status --short` (the nested template repo), resolved to template/.claude/workflows/<file> — even if not in allScope' },
    offendingUndeclaredImports: { type: 'array', items: { type: 'string' }, description: 'GH-118/LRN-119/RT-001: resolved import targets (absolute agent_sdk.* OR relative from ./from ..) of dirty/scope .py files that are untracked (git ls-files empty) AND absent from wave.allScope' },
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
  '  Todos that Depends: on another todo in the SAME group do not add a dep entry.\n' +
  '  Format: {"A": [], "B": ["A"], ...}\n\n' +
  'Return structured data.',
  { schema: WAVE_SCHEMA, label: 'parse', phase: 'Parse' }
)

if (!wave) {
  log('ERROR: could not parse wave file at ' + WAVE_FILE)
  return { error: 'parse-failed' }
}

// Unified review scope = Creates: ∪ Modifies: paths. Modify-only waves (0 Creates,
// >0 Modifies) are legitimate (e.g. skill/doc-only waves) — deriving scope from
// Creates: alone false-aborts them here AND lands them with empty adversarial-review
// and protocol-audit scope downstream. Always union both. (RT-001 / LRN-053)
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

// WC-RT-005: lrnBase is a snapshot taken at Parse time. Concurrent wave runs (e.g., two
// terminals each executing /wave with explicit waveIds) will read the same lrnNext and
// produce identical LRN IDs, silently overwriting each other's learning files. Run waves
// sequentially — /wave without an explicit waveId executes sequentially by design; parallel
// explicit-wave invocations are unsupported. Detect concurrent runs by checking for
// workspace/todos/active/.wave-lock before starting a wave if this invariant must be enforced.
const lrnBase          = wave.lrnNext
const allHighFindings  = []   // accumulates critical/high for codify phase
let   protocolBlocked      = false
let   testsRed             = false
let   testsBlockedArchive  = false   // RT-003: tracks when a red test suite (not protocol) blocks archive
let   archivePlanRowMissing = false  // LRN-062 / RT-001: plan.md ledger row still missing after self-heal
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
    // Circular or unresolvable dep — write a deferred note so the operator can inspect,
    // then fall back to the first remaining group to avoid an infinite loop.
    const fallbackLabel = remainingGroups[0].label
    log('WARNING: unresolvable group dependency detected — circular dep chain likely. ' +
        'Writing deferred note and falling back to sequential for group ' + fallbackLabel)
    await agent(
      'Write workspace/todos/deferred/' + wave.waveId + '-circular-dep-' + fallbackLabel + '.md\n\n' +
      'Include: wave ID (' + wave.waveId + '), date (' + TODAY + '), group (' + fallbackLabel + '),\n' +
      'reason: circular or unresolvable groupDeps — no group was ready to run.\n' +
      'Remaining groups: ' + remainingGroups.map(function(g) { return g.label }).join(', ') + '.\n' +
      'Instruction: "Inspect groupDeps in the wave file for cycles, fix them, ' +
      'then re-run /wave ' + wave.waveId + '."',
      { label: 'defer:circ-dep:' + fallbackLabel, phase: 'Implement' }
    )
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
  // WC-RT-006: use a const function expression — block-scoped function declarations have
  // engine-dependent semantics inside while loops in ES module strict mode.
  const makeGroupThunk = function(group) {
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
      'Scope (Creates: AND Modifies: paths for this group):\n' + group.scope.join('\n') + '\n\n' +
      'Also check their transitive callers and importers.\n\n' +
      'Run all 8 dimensions from agents/core/redteam.md. Include the SDK Security\n' +
      'Invariants (SI-1…SI-7) in the security dimension — fail closed.\n\n' +
      'Return structured findings.',
      { schema: RT_SCHEMA, label: 'rt:unit:' + group.label + ':r' + uRound, phase: 'Unit Redteam',
        agentType: 'redteam' }
    )

    // RT-004: null redteam response is unknown state — must not be treated as clean (fail-open).
    // Log a warning and continue without updating prevSigs so stall detection against
    // the most recent real finding set remains intact. Resetting prevSigs on null would
    // defeat stall detection: a null round followed by a round with the same findings as
    // the prior real round would not trigger sigsEqual because prevSigs was cleared.
    // WC-002: also enforce the budget cap on null rounds so persistent null responses
    // cannot loop indefinitely — the budget check is mirrored here before the continue.
    if (!rt) {
      log('WARNING: unit redteam agent returned null for group ' + group.label + ' round ' + uRound + ' — treating as unknown (not clean); preserving last known sig set')
      if (uRound >= 5) {
        log('Null responses exceeded round budget for group ' + group.label + ' — deferring')
        await agent(
          'Write workspace/todos/deferred/' + wave.waveId + '-group-' + group.label + '-rt-null-budget.md\n\n' +
          'Include: wave ID (' + wave.waveId + '), group (' + group.label + '), date (' + TODAY + '),\n' +
          'round (' + uRound + '), reason: unit redteam agent returned null on every round — unknown state.\n' +
          'Instruction: "Re-run /wave ' + wave.waveId + ' to retry unit redteam for this group."',
          { label: 'defer:unit:' + group.label + ':rt-null-budget', phase: 'Unit Redteam' }
        )
        break
      }
      // Do NOT reset prevSigs — preserve the last real finding set so stall detection
      // fires correctly on the next round if findings have not changed.
      continue
    }

    // WC-RT-004: cross-validate findingsCount against findings.length — an agent returning
    // findingsCount=0 with a non-empty array would break clean despite real findings.
    if (rt.findingsCount === 0 && rt.findings.length > 0) {
      log('WARNING: findingsCount=0 but findings array has ' + rt.findings.length + ' item(s) — treating as non-clean')
      rt.findingsCount = rt.findings.length
    }

    if (rt.findingsCount === 0) {
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

    // RT-006: Debug fires unconditionally at round 4+ (uRound > 3), and at any round when stall
    // is detected (same findings as previous round). Round 5 exits via deferred note above.
    if (uRound > 3 || stalled) {
      log((stalled ? 'Stall detected — ' : 'Round 4+ — ') + 'escalating to debug agent')
      await agent(
        'Fix-loop requires fresh-lens analysis' + (stalled ? ' (stalled: same findings across 2 rounds)' : ' (round ' + uRound + ')') + '.\n\n' +
        'Prior findings:\n' + JSON.stringify(rt.findings, null, 2) + '\n\n' +
        'Scope:\n' + group.scope.join('\n') + '\n\n' +
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

    // GH-19: consume gate result — red suite blocks loop continuation.
    // RT-001: fail-closed — null gate response is unknown state, treated as failure.
    const unitGate = await agent(
      'Run: python -m pytest -q\n' +
      'Report: exitCode (0=pass, non-zero=fail), passCount, failCount, and failures (list of\n' +
      '"test_file.py::test_name: reason" strings for each failing test). Return all fields.',
      { schema: GATE_SCHEMA, label: 'gate:unit:' + group.label + ':r' + uRound, phase: 'Unit Redteam' }
    )
    if (!unitGate) {
      log('WARNING: unit gate agent returned null for group ' + group.label + ' round ' + uRound + ' — treating as gate failure (unknown state)')
      testsRed = true
      // WC-003: write a deferred note so the operator has a durable artifact indicating
      // which group's gate failed, the round, and how to retry. Every other loop-exit
      // path writes a deferred note; this path must too (RT-002: null gate blocks loop).
      await agent(
        'Write workspace/todos/deferred/' + wave.waveId + '-group-' + group.label + '-gate-null-r' + uRound + '.md\n\n' +
        'Include: wave ID (' + wave.waveId + '), group (' + group.label + '), date (' + TODAY + '),\n' +
        'round (' + uRound + '), reason: unit gate agent returned null (unknown test state).\n' +
        'Instruction: "Re-run /wave ' + wave.waveId + ' to retry gate for this group."',
        { label: 'defer:unit:' + group.label + ':gate-null:r' + uRound, phase: 'Unit Redteam' }
      )
      // RT-002: null gate blocks loop continuation — do not silently proceed.
      break
    }
    if (unitGate.exitCode !== 0) {
      testsRed = true
      log('Gate RED (' + unitGate.failCount + ' failing) — dispatching test-fix agent')
      await agent(
        'Fix the failing tests below. Read the test file and the source it covers.\n' +
        'Failing tests:\n' + unitGate.failures.join('\n') + '\n\n' +
        'Run `python -m pytest -q <failing-test-file>` to confirm GREEN before finishing.',
        { label: 'fix:tests:unit:' + group.label + ':r' + uRound, phase: 'Unit Redteam' }
      )
      // RT-002: re-gate after test-fix to verify the fix succeeded before continuing the loop.
      const unitReGate = await agent(
        'Run: python -m pytest -q\n' +
        'Report: exitCode (0=pass, non-zero=fail), passCount, failCount, and failures (list of\n' +
        '"test_file.py::test_name: reason" strings for each failing test). Return all fields.',
        { schema: GATE_SCHEMA, label: 'gate:unit:' + group.label + ':r' + uRound + ':recheck', phase: 'Unit Redteam' }
      )
      // RT-001: fail-closed — null re-gate is still unknown, treat as red.
      if (!unitReGate || unitReGate.exitCode !== 0) {
        const failCount = unitReGate ? unitReGate.failCount : '?'
        log('Re-gate still RED (' + failCount + ' failing) after test-fix — deferring group ' + group.label)
        await agent(
          'Write workspace/todos/deferred/' + wave.waveId + '-group-' + group.label + '-tests-red-r' + uRound + '.md\n\n' +
          'Include: wave ID (' + wave.waveId + '), group (' + group.label + '), date (' + TODAY + '),\n' +
          'round (' + uRound + '), reason: test suite RED after fix attempt.\n' +
          'Instruction: "Fix failing tests and re-run /wave ' + wave.waveId + '".',
          { label: 'defer:unit:' + group.label + ':tests-red:r' + uRound, phase: 'Unit Redteam' }
        )
        break
      }
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
    'Scope (all Creates: AND Modifies: paths across every group):\n' +
    wave.allScope.join('\n') + '\n\n' +
    'Also check transitive callers and importers. Re-expand scope every round.\n\n' +
    'Run all 8 dimensions. SDK Security Invariants (SI-1…SI-7) fail closed.\n\n' +
    'Return structured findings.',
    { schema: RT_SCHEMA, label: 'rt:phase:r' + pRound, phase: 'Phase Redteam',
      agentType: 'redteam' }
  )

  // RT-004: null redteam response is unknown state — must not be treated as clean (fail-open).
  // WC-002: also enforce the budget cap on null rounds so persistent null responses
  // cannot loop indefinitely — the budget check is mirrored here before the continue.
  if (!rt) {
    log('WARNING: phase redteam agent returned null at round ' + pRound + ' — treating as unknown (not clean)')
    if (pRound >= 8) {
      log('Null responses exceeded phase round budget — deferring')
      await agent(
        'Write workspace/todos/deferred/' + wave.waveId + '-phase-rt-null-budget.md\n\n' +
        'Include: wave ID (' + wave.waveId + '), date (' + TODAY + '),\n' +
        'round (' + pRound + '), reason: phase redteam agent returned null on every round — unknown state.\n' +
        'Instruction: "Re-run /wave ' + wave.waveId + ' to retry phase redteam."',
        { label: 'defer:phase:rt-null-budget', phase: 'Phase Redteam' }
      )
      break
    }
    // RT-004: do NOT reset prevSigs — preserve the last real finding set so stall detection
    // fires correctly on the next round if findings have not changed. Resetting prevSigs here
    // would defeat stall detection: a null round followed by a round with the same findings as
    // the prior real round would not trigger sigsEqual because prevSigs was cleared.
    // continue to next round — do not fall through to fix/debug logic; prevSigs not reset so stall detection remains valid
    continue
  }

  // WC-RT-004: cross-validate findingsCount against findings.length.
  if (rt.findingsCount === 0 && rt.findings.length > 0) {
    log('WARNING: findingsCount=0 but findings array has ' + rt.findings.length + ' item(s) — treating as non-clean')
    rt.findingsCount = rt.findings.length
  }

  if (rt.findingsCount === 0) {
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

  // RT-006: Debug fires unconditionally at round 4+ (pRound > 3), and at any round when stall
  // is detected (same findings as previous round). Round 8 exits above.
  if (pRound > 3 || pStalled) {
    log((pStalled ? 'Stall detected — ' : 'Round 4+ — ') + 'escalating to debug agent')
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

  // GH-19: consume gate result — red suite blocks loop continuation.
  // RT-001: fail-closed — null gate response is unknown state, treated as failure.
  const phaseGate = await agent(
    'Run: python -m pytest -q\n' +
    'Report: exitCode (0=pass, non-zero=fail), passCount, failCount, and failures (list of\n' +
    '"test_file.py::test_name: reason" strings for each failing test). Return all fields.',
    { schema: GATE_SCHEMA, label: 'gate:phase:r' + pRound, phase: 'Phase Redteam' }
  )
  if (!phaseGate) {
    log('WARNING: phase gate agent returned null at round ' + pRound + ' — treating as gate failure (unknown state)')
    testsRed = true
    // WC-003: write a deferred note so the operator has a durable artifact indicating
    // which round's gate failed and how to retry. Mirrors the unit loop null-gate path.
    await agent(
      'Write workspace/todos/deferred/' + wave.waveId + '-phase-gate-null-r' + pRound + '.md\n\n' +
      'Include: wave ID (' + wave.waveId + '), date (' + TODAY + '),\n' +
      'round (' + pRound + '), reason: phase gate agent returned null (unknown test state).\n' +
      'Instruction: "Re-run /wave ' + wave.waveId + ' to retry phase gate."',
      { label: 'defer:phase:gate-null:r' + pRound, phase: 'Phase Redteam' }
    )
    // RT-002: null gate blocks loop continuation — do not silently proceed.
    break
  }
  if (phaseGate.exitCode !== 0) {
    testsRed = true
    log('Gate RED (' + phaseGate.failCount + ' failing) — dispatching test-fix agent')
    await agent(
      'Fix the failing tests below. Read the test file and the source it covers.\n' +
      'Failing tests:\n' + phaseGate.failures.join('\n') + '\n\n' +
      'Run `python -m pytest -q <failing-test-file>` to confirm GREEN before finishing.',
      { label: 'fix:tests:phase:r' + pRound, phase: 'Phase Redteam' }
    )
    // RT-002: re-gate after test-fix to verify the fix succeeded before continuing the loop.
    const phaseReGate = await agent(
      'Run: python -m pytest -q\n' +
      'Report: exitCode (0=pass, non-zero=fail), passCount, failCount, and failures (list of\n' +
      '"test_file.py::test_name: reason" strings for each failing test). Return all fields.',
      { schema: GATE_SCHEMA, label: 'gate:phase:r' + pRound + ':recheck', phase: 'Phase Redteam' }
    )
    // RT-001: fail-closed — null re-gate is still unknown, treat as red and stop the loop.
    if (!phaseReGate || phaseReGate.exitCode !== 0) {
      const failCount = phaseReGate ? phaseReGate.failCount : '?'
      log('Re-gate still RED (' + failCount + ' failing) after test-fix — stopping phase redteam loop')
      await agent(
        'Write workspace/todos/deferred/' + wave.waveId + '-phase-tests-red-r' + pRound + '.md\n\n' +
        'Include: wave ID (' + wave.waveId + '), date (' + TODAY + '),\n' +
        'round (' + pRound + '), reason: test suite RED after fix attempt.\n' +
        'Instruction: "Fix failing tests and re-run /wave ' + wave.waveId + '".',
        { label: 'defer:phase:tests-red:r' + pRound, phase: 'Phase Redteam' }
      )
      break
    }
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
        wave.allScope.filter(function(p) {
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
        wave.allScope.filter(function(p) {
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
        // LRN-012: Keep in sync with DESIGN.md §5.4 and agent_sdk/models/content_types.py — single logical unit
        // WC-RT-003: Core 6 + Extended 8 = 14 FROZEN; 4 RESERVED (TradeActivity, CompanyInfo, DealList, InvestorProfile) never emitted.
        'Check: createSurface/updateComponents/updateDataModel/deleteSurface shapes,\n' +
        'Core 6 + Extended 8 Standard Profile types only (14 FROZEN total; 4 RESERVED: TradeActivity, CompanyInfo, DealList, InvestorProfile — never emitted), JSON-Pointer binding,\n' +
        'A2A DataPart delivery, translator.py message types, field contracts.\n\n' +
        'Return structured findings. Set protocol="A2UI" per finding.',
        { schema: PROTO_SCHEMA, agentType: 'a2ui-advisor', label: 'proto:a2ui', phase: 'Protocol Audit' }
      )
    })
  }

  // Seam check: no specialist agentType — it reads multiple protocol surfaces together,
  // so no single advisor owns it. Uses the default agent with full cross-surface context.
  // RT-005: derive seam paths from allScope (Creates: ∪ Modifies:) rather than hardcoding —
  // hardcoded paths silently produce empty results when routes live at different paths or are not yet created.
  // RT-001: dispatched unconditionally whenever this block runs at all — it only runs
  // inside the `if (runProtocol)` branch above — matching sdk-wave.js, which never gates
  // its seam task on a marker list. Previously this leg was ALSO gated on
  // seamPaths.length > 0, so a wave touching only a file promoted into a protocol-surface
  // array but not matched by SEAM_ROUTE_MARKERS (e.g. AUTH_SURFACE's src/auth/middleware)
  // skipped the seam audit — the one leg that checks "Auth mode enforced uniformly: no
  // surface accepts a token type another rejects", the check most relevant to that class
  // of change. seamPaths is still only a HINT that narrows the "files to audit" line in the
  // prompt; it no longer gates whether the task runs — wave.allScope is always given in full.
  // RT-001 (round-7 fresh-lens): markers are matched as WHOLE path segments — a file
  // basename minus its extension, or a directory name — NOT as substrings. This delivers
  // the segment-boundary match the earlier leading-slash markers ('/mcp', '/a2a', …) only
  // half-provided: a leading slash anchors a segment's START but not its END, so '/mcp'
  // still prefix-matched '/mcptools' and '/a2a' matched 'pseudoa2a'. Whole-segment matching
  // makes both non-matches — 'mcptools'/'pseudoa2a' are not the segments 'mcp'/'a2a' — and
  // needs no 'auth'-fragment marker: the OAuth route routes/oauth is caught by the 'routes'
  // segment, while the credential store auth/oauth_tokens (a non-route AUTH_SURFACE member)
  // is correctly excluded, ending the round-4 asymmetric mislabel at its source. The heading
  // below stays "Candidate route/shared surfaces" so a matched non-HTTP shared surface
  // (e.g. src/a2ui/… via the 'a2ui' segment) is not described as a route file.
  const SEAM_ROUTE_MARKERS = ['routes', 'a2a', 'mcp', 'agent_card', 'ag_ui', 'a2ui']
  const seamPaths = wave.allScope.filter(function(p) {
    return p.split('/').some(function(seg) {
      return SEAM_ROUTE_MARKERS.indexOf(seg.replace(/\.[^./]+$/, '')) !== -1
    })
  })
  advisorTasks.push(function() {
    return agent(
      'Cross-protocol seam audit — consistency ACROSS A2A, MCP, AG-UI, A2UI surfaces.\n\n' +
      'Candidate route/shared surfaces in scope (derived from wave scope):\n' +
      (seamPaths.length > 0 ? seamPaths.join('\n') : '(none matched by name — shared/auth surface change; see full scope below)') + '\n\n' +
      'Wave scope paths (Creates: ∪ Modifies:):\n' + wave.allScope.join('\n') + '\n\n' +
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
    // RT-001: fail-closed — null protoFixGate is unknown state, treated as failure.
    // RT-003: also set testsBlockedArchive so the archive-skip message correctly
    // attributes the block to a gate-infrastructure failure, not a protocol finding.
    if (!protoFixGate) {
      log('WARNING: proto:fix gate agent returned null — treating as gate failure (unknown state); archive will be blocked')
      testsRed = true
      protocolBlocked = true
      testsBlockedArchive = true
    } else if (protoFixGate.exitCode !== 0) {
      testsRed = true
      log('Gate RED after proto:fix (' + protoFixGate.failCount + ' failing) — dispatching test-fix agent')
      await agent(
        'Fix the failing tests introduced by the protocol fix. Read the test file and source.\n' +
        'Failing tests:\n' + protoFixGate.failures.join('\n') + '\n\n' +
        'Run `python -m pytest -q <failing-test-file>` to confirm GREEN before finishing.',
        { label: 'fix:tests:proto:fix', phase: 'Protocol Audit' }
      )
      // WC-RT-002: re-gate after proto test-fix — unit and phase loops each have a formal
      // re-gate (unitReGate/phaseReGate); the proto path must too. A failed test-fix that
      // silently proceeds to the recheck (and then to archive) defeats zero-tolerance.
      const protoTestReGate = await agent(
        'Run: python -m pytest -q\n' +
        'Report: exitCode (0=pass, non-zero=fail), passCount, failCount, and failures (list of\n' +
        '"test_file.py::test_name: reason" strings for each failing test). Return all fields.',
        { schema: GATE_SCHEMA, label: 'gate:proto:fix:recheck', phase: 'Protocol Audit' }
      )
      // RT-001: fail-closed — null re-gate is unknown state, treated as failure.
      if (!protoTestReGate || protoTestReGate.exitCode !== 0) {
        const failCount = protoTestReGate ? protoTestReGate.failCount : '?'
        log('Proto re-gate still RED (' + failCount + ' failing) after test-fix — blocking recheck; archive will be blocked')
        testsBlockedArchive = true
        protocolBlocked = true
        await agent(
          'Write workspace/todos/deferred/' + wave.waveId + '-proto-tests-red.md\n\n' +
          'Include: wave ID (' + wave.waveId + '), date (' + TODAY + '),\n' +
          'reason: test suite RED after protocol test-fix attempt.\n' +
          'Instruction: "Fix failing tests and re-run /wave ' + wave.waveId + '".',
          { label: 'defer:proto:tests-red', phase: 'Protocol Audit' }
        )
        // Do not proceed to the protocol recheck — tests are red.
        // Jump out of the if-block; protocolBlocked will skip archive.
      }
    }

    // WC-RT-005: skip recheck if protocolBlocked was set by protoFixGate=null or
    // protoTestReGate failure — both paths already wrote a deferred note. Dispatching
    // N advisor agents when tests are red wastes calls and produces misleading output.
    if (!protocolBlocked) {

    // Recheck: same parallel advisor dispatch as the initial audit (including seam)
    const recheckTasks = []
    if (runA2A) {
      recheckTasks.push(function() {
        return agent(
          'A2A v0.3.0 re-audit after preceding fix. Check same surfaces.\n' +
          'Scope paths (Creates: ∪ Modifies:):\n' + wave.allScope.join('\n') + '\n' +
          'Focus on previously-critical findings. Return structured findings.',
          { schema: PROTO_SCHEMA, agentType: 'a2a-advisor', label: 'proto:recheck:a2a', phase: 'Protocol Audit' }
        )
      })
    }
    if (runMCP) {
      recheckTasks.push(function() {
        return agent(
          'MCP re-audit after preceding fix. Check same surfaces.\n' +
          'Scope paths (Creates: ∪ Modifies:):\n' + wave.allScope.join('\n') + '\n' +
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
    // Seam recheck: no specialist agentType for the same reason as the initial seam check.
    // RT-001: pushed unconditionally, mirroring the initial seam task above — previously
    // gated on seamPaths.length > 0, the same gap the initial-dispatch fix removes there.
    recheckTasks.push(function() {
      return agent(
        'Cross-protocol seam re-audit after preceding fix.\n' +
        'Candidate route/shared surfaces in scope:\n' +
        (seamPaths.length > 0 ? seamPaths.join('\n') : '(none matched by name — shared/auth surface change; see full scope below)') + '\n' +
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
        '"Fix protocol findings, then run /agent-verify, then re-run /wave ' + wave.waveId + '".',
        { label: 'proto:defer-note', phase: 'Protocol Audit' }
      )
    }

    } // end if (!protocolBlocked) — recheck guard
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

// ─── SDK issue scan (sequential, before LRN capture) ─────────────────────────
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

// GH-22: pre-archive gate — suite must be green before marking wave complete.
// RT-001: fail-closed — null preArchiveGate is unknown state; archive must be blocked.
const preArchiveGate = await agent(
  'Run: python -m pytest -q\n' +
  'Report: exitCode (0=pass, non-zero=fail), passCount, failCount, and failures (list of\n' +
  '"test_file.py::test_name: reason" strings for each failing test). Return all fields.',
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

// GH-40 / GH-84: pre-archive commit check — all scope files (Creates: ∪ Modifies:) plus any
// harness deliverable directories must be committed before archive. A wave that archives
// with deliverables only in the working tree will silently lose them on `git checkout`.
// GH-118 (LRN-119): step 5 below adds an import cross-check — a module extracted mid-wave
// that is untracked, imported by a declared file, but absent from wave.allScope AND outside
// the harness dirs produced no offending entry under the checks above and silently passed
// this gate, risking an ImportError at boot on every importing surface. See
// offendingUndeclaredImports on ARCHIVE_INTENT_SCHEMA above.
// RT-001: step 5 also resolves RELATIVE intra-package imports (`from ..pkg.mod import X`),
// not only absolute `agent_sdk.*` imports. Relative imports are the dominant style inside
// agent_sdk/routes/ — the canonical LRN-119 module (agent_sdk/common/origin.py) is imported
// there as `from ..common.origin import guard_origin`, which an absolute-only scan misses
// entirely, defeating the gate on its own motivating scenario.
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
    '   tests/, workspace/learning/, workspace/scenarios/results/, workspace/prd/,\n' +
    '   .claude/workflows/, or harness/workflows/\n' +
    '   — put these in offendingHarnessPaths even if they do not appear in the scope list.\n' +
    '4b. RT-001 (w036): template/.claude/workflows/ is a THIRD byte-identical mirror\n' +
    '   (synced via test_workflow_sync.py) but lives inside template/, a nested peer git\n' +
    '   repo that is gitignored in THIS repo — step 1\'s `git status --short` can NEVER\n' +
    '   show a path under template/, no matter how dirty that nested repo\'s working tree\n' +
    '   is, so it cannot be folded in via step 4 above. If a `template/` directory exists\n' +
    '   at the repo root, separately run: git -C template status --short\n' +
    '   For each line in THAT output whose path starts with .claude/workflows/, add\n' +
    '   `template/` + that path (e.g. template/.claude/workflows/wave-cycle.js) to\n' +
    '   offendingHarnessPaths. This is the only way this gate can see an uncommitted\n' +
    '   template mirror — the mirror lives in a repo the top-level git status cannot see.\n' +
    '5. GH-118 import cross-check (LRN-119 — mid-wave module extraction). RT-001: this step\n' +
    '   MUST resolve RELATIVE intra-package imports (`from . import X`, `from .mod import Y`,\n' +
    '   `from ..pkg.mod import Z`) in addition to ABSOLUTE `agent_sdk.*` imports. Relative\n' +
    '   imports are the dominant style inside agent_sdk/routes/ (e.g.\n' +
    '   `from ..common.origin import guard_origin`) — a scan that resolves only absolute\n' +
    '   imports misses the canonical case this gate exists to catch, and quietly passes:\n' +
    '   a. Identify every dirty or untracked .py file from the git status output.\n' +
    '   b. For each .py file that is dirty/untracked OR listed in the scope above, read every\n' +
    '      import statement in it — both ABSOLUTE (`import agent_sdk...`,\n' +
    '      `from agent_sdk... import ...`) and RELATIVE (`from . import ...`,\n' +
    '      `from .mod import ...`, `from ..pkg.mod import ...`) — and resolve any intra-\n' +
    '      package target, whether spelled absolutely OR relatively, to the local .py file it\n' +
    '      names. Four forms, resolved differently:\n' +
    '        - ABSOLUTE, direct module: `import agent_sdk.<dotted-path>` (one or more dotted\n' +
    '          segments — a SINGLE segment counts too, e.g. `import agent_sdk.foo`) → resolve\n' +
    '          directly to `agent_sdk/<dotted-path-with-/-for-.>.py` (e.g.\n' +
    '          `agent_sdk.common.origin` → `agent_sdk/common/origin.py`; `agent_sdk.foo` →\n' +
    '          `agent_sdk/foo.py`).\n' +
    '        - ABSOLUTE, from-import: `from agent_sdk[.<pkg-path>] import <name>` where\n' +
    '          <pkg-path> is ZERO or more dotted segments at ANY depth — zero segments covers\n' +
    '          the bare top-level form `from agent_sdk import <name>` → do NOT assume this\n' +
    '          resolves to `agent_sdk/<pkg-path>/__init__.py`. First check whether\n' +
    '          `agent_sdk/<pkg-path>/<name>.py` exists on disk (`<name>` is itself a submodule\n' +
    '          file at that depth; when <pkg-path> is empty, check `agent_sdk/<name>.py`\n' +
    '          directly), e.g. `from agent_sdk.common import origin` → check for\n' +
    '          `agent_sdk/common/origin.py`. If the submodule file exists, resolve to it — this\n' +
    '          is the case a mid-wave extraction produces, and the one this gate exists to\n' +
    '          catch, no matter how many package levels deep the extraction landed. RT-001\n' +
    '          (round-5): otherwise <name> may be a SUB-PACKAGE (a directory with its own\n' +
    '          `__init__.py`) rather than a submodule file — check whether\n' +
    '          `agent_sdk/<pkg-path>/<name>/__init__.py` exists on disk (when <pkg-path> is\n' +
    '          empty, check `agent_sdk/<name>/__init__.py` directly); if it exists, <name> is\n' +
    '          a sub-package and resolves to THAT file, e.g. `from agent_sdk import routes` →\n' +
    '          `agent_sdk/routes.py` does NOT exist, but `agent_sdk/routes/__init__.py` DOES\n' +
    '          (agent_sdk/routes/ is a package) → resolves to `agent_sdk/routes/__init__.py`.\n' +
    '          RT-004: otherwise, when <pkg-path> is NON-EMPTY, check whether\n' +
    '          `agent_sdk/<pkg-path>.py` exists on disk — <pkg-path> itself names a MODULE and\n' +
    '          <name> is a symbol inside it (the from-clause names the module fully), e.g.\n' +
    '          `from agent_sdk.common.origin import guard_origin` → <pkg-path> is\n' +
    '          `common.origin`; neither `agent_sdk/common/origin/guard_origin.py` nor\n' +
    '          `agent_sdk/common/origin/guard_origin/__init__.py` exists, but\n' +
    '          `agent_sdk/common/origin.py` DOES → resolves to `agent_sdk/common/origin.py`,\n' +
    '          NEVER to the nonexistent `agent_sdk/common/origin/__init__.py`. Only resolve to\n' +
    '          `agent_sdk/<pkg-path>/__init__.py` as the ENCLOSING package (i.e. `<name>` is a\n' +
    '          symbol re-exported from it, not a submodule, sub-package, or module) when NONE\n' +
    '          of `agent_sdk/<pkg-path>/<name>.py`, `agent_sdk/<pkg-path>/<name>/__init__.py`,\n' +
    '          nor (when <pkg-path> is non-empty) `agent_sdk/<pkg-path>.py` exists.\n' +
    '        - RELATIVE, from-import with a module path: `from <dots><module-path> import\n' +
    '          <name>` where <dots> is one or more leading dots and <module-path> is a\n' +
    '          NON-EMPTY dotted path immediately following the dots (e.g.\n' +
    '          `from ..common.origin import guard_origin`, `from ..credentials import forwarding`,\n' +
    '          or `from .mod import Y`) → resolve the dots against the\n' +
    '          directory that CONTAINS the importing file: one dot means that directory\n' +
    '          itself; each additional dot walks up one more parent directory from there.\n' +
    '          Append <module-path> (with `.` replaced by `/`) to that directory to get\n' +
    '          <pkg-path>. Then disambiguate <name> using the SAME four-way on-disk order as\n' +
    '          the ABSOLUTE from-import form above — never resolve straight to `<pkg-path>.py`\n' +
    '          or straight to `<pkg-path>/__init__.py`: FIRST check whether\n' +
    '          `<pkg-path>/<name>.py` exists on disk (<name> is itself a submodule file under\n' +
    '          the <module-path> package) and resolve to THAT if it exists. RT-004: otherwise\n' +
    '          check whether `<pkg-path>/<name>/__init__.py` exists on disk (<name> is a\n' +
    '          SUB-PACKAGE — e.g. a freshly-extracted, still-untracked sub-package) and resolve\n' +
    '          to THAT if it exists. Otherwise check whether `<pkg-path>.py` exists on disk\n' +
    '          (<pkg-path> itself names a MODULE and <name> is a symbol inside it) and resolve\n' +
    '          to THAT if it exists. Only when NONE of those three exist does `<name>` resolve\n' +
    '          as a symbol re-exported from a package, in which case resolve to\n' +
    '          `<pkg-path>/__init__.py`. Worked example (symbol-from-module):\n' +
    '          `from ..common.origin import guard_origin` inside `agent_sdk/routes/a2a.py` —\n' +
    '          that file lives in `agent_sdk/routes`, one dot keeps that directory, the second\n' +
    '          dot walks up to `agent_sdk`; appending `common/origin` gives <pkg-path>\n' +
    '          `agent_sdk/common/origin`; neither `agent_sdk/common/origin/guard_origin.py`\n' +
    '          nor `agent_sdk/common/origin/guard_origin/__init__.py` exists, but\n' +
    '          `agent_sdk/common/origin.py` DOES → resolves to `agent_sdk/common/origin.py`.\n' +
    '          Worked example (submodule, RT-001):\n' +
    '          `from ..credentials import forwarding` inside `agent_sdk/routes/a2a.py` —\n' +
    '          <pkg-path> is `agent_sdk/credentials`; `agent_sdk/credentials/forwarding.py`\n' +
    '          DOES exist, so `forwarding` is a submodule and this resolves to that tracked\n' +
    '          file — NEVER to the nonexistent `agent_sdk/credentials.py`, which would be a\n' +
    '          false-positive undeclared-import block on every wave that scopes a route file.\n' +
    '          Worked example (sub-package, RT-004): `from ..common import newsubpkg` inside\n' +
    '          `agent_sdk/routes/a2a.py` — <pkg-path> is `agent_sdk/common`;\n' +
    '          `agent_sdk/common/newsubpkg.py` does NOT exist, but\n' +
    '          `agent_sdk/common/newsubpkg/__init__.py` DOES → resolves to that file, not to\n' +
    '          the nonexistent `agent_sdk/common.py` a two-step ladder would have stopped at.\n' +
    '        - RELATIVE, bare: `from <dots> import <name>` where <dots> is one or more\n' +
    '          leading dots with NO module path after them (e.g. `from . import origin`\n' +
    '          inside `agent_sdk/common/foo.py`) → resolve the dots to a base directory\n' +
    '          exactly as in the relative from-import form above, then check whether\n' +
    '          `<base-dir>/<name>.py` exists on disk. If it exists, resolve to that file —\n' +
    '          <name> is itself a submodule directly under that directory. RT-001 (round-5):\n' +
    '          otherwise <name> may be a SUB-PACKAGE (a directory with its own `__init__.py`)\n' +
    '          rather than a submodule file — check whether `<base-dir>/<name>/__init__.py`\n' +
    '          exists on disk; if it exists, resolve to THAT file, e.g. `from . import routes`\n' +
    '          inside `agent_sdk/__init__.py` → `<base-dir>/routes.py` does NOT exist, but\n' +
    '          `<base-dir>/routes/__init__.py` DOES → resolves to it. Only resolve to\n' +
    '          `<base-dir>/__init__.py` as the ENCLOSING package (i.e. `<name>` is a symbol\n' +
    '          re-exported from it) when NEITHER `<base-dir>/<name>.py` NOR\n' +
    '          `<base-dir>/<name>/__init__.py` exists.\n' +
    '      Ignore stdlib and third-party imports. Resolve any intra-package target — whether\n' +
    '      spelled ABSOLUTELY (rooted at `agent_sdk`) OR RELATIVELY (`from .`, `from ..`,\n' +
    '      etc.) — do not skip relative forms just because they do not start with\n' +
    '      `agent_sdk`.\n' +
    '   c. For each resolved path, decide offender status. A resolved path is an offender\n' +
    '      ONLY when ALL THREE hold: (i) it actually EXISTS on disk — the LRN-119 mid-wave-\n' +
    '      extraction failure mode is a module that is PRESENT locally (so the import works\n' +
    '      now) but untracked (so it vanishes on `git checkout`); (ii) `git ls-files <path>`\n' +
    '      produces NO output (the file is untracked); and (iii) the path does not appear in\n' +
    '      the scope list above. Add offenders to offendingUndeclaredImports. A resolved path\n' +
    '      that does NOT exist on disk is a mis-resolution (or a genuine broken import the\n' +
    '      RED-suite pre-archive gate already blocks on), never a mid-wave-extracted module —\n' +
    '      NEVER flag it (RT-001: guards against a from-import whose <name> submodule is\n' +
    '      mis-resolved to a nonexistent `<pkg>.py`). A resolved path that IS tracked\n' +
    '      (git ls-files returns it) is never an offender either, even if it was also\n' +
    '      modified — only newly-untracked local modules internal to this package that are\n' +
    '      present on disk qualify, regardless of whether they were imported absolutely or\n' +
    '      relatively.\n' +
    '6. Return all five fields.\n\n' +
    'If the working tree is completely clean, gitStatusOutput is empty string,\n' +
    'dirtyPaths is [], offendingPaths is [], offendingHarnessPaths is [],\n' +
    'offendingUndeclaredImports is [].',
    { schema: ARCHIVE_INTENT_SCHEMA, label: 'gate:archive-commit', phase: 'Archive' }
  )

  // WC-001: null archiveIntent must block archive — unknown commit state is not the same as clean.
  // All other null-agent responses in this file use the same fail-closed invariant (RT-001).
  if (!archiveIntent) {
    protocolBlocked = true
    log('WARNING: archive-commit gate agent returned null — archive BLOCKED (unknown commit state). Re-run /wave ' + wave.waveId)
  } else if ((archiveIntent.offendingPaths && archiveIntent.offendingPaths.length > 0) ||
             (archiveIntent.offendingHarnessPaths && archiveIntent.offendingHarnessPaths.length > 0) ||
             (archiveIntent.offendingUndeclaredImports && archiveIntent.offendingUndeclaredImports.length > 0)) {
    protocolBlocked = true
    if (archiveIntent.offendingPaths && archiveIntent.offendingPaths.length > 0) {
      log('Archive BLOCKED — ' + archiveIntent.offendingPaths.length + ' scope file(s) are uncommitted:')
      archiveIntent.offendingPaths.forEach(function(p) { log('  [uncommitted] ' + p) })
    }
    if (archiveIntent.offendingHarnessPaths && archiveIntent.offendingHarnessPaths.length > 0) {
      log('Archive BLOCKED — ' + archiveIntent.offendingHarnessPaths.length + ' harness deliverable(s) are uncommitted:')
      archiveIntent.offendingHarnessPaths.forEach(function(p) { log('  [uncommitted] ' + p) })
    }
    if (archiveIntent.offendingUndeclaredImports && archiveIntent.offendingUndeclaredImports.length > 0) {
      // GH-118 / LRN-119: a module extracted mid-wave that a declared file imports, but
      // which is itself untracked and outside wave.allScope — staging only declared paths
      // would ship an ImportError at boot on every importing surface.
      log('Archive BLOCKED — ' + archiveIntent.offendingUndeclaredImports.length + ' undeclared module(s) are imported by scope files:')
      archiveIntent.offendingUndeclaredImports.forEach(function(p) { log('  [undeclared import] ' + p) })
      log('Add the module(s) above to Creates: in the wave/todo and stage them explicitly, then re-run /wave ' + wave.waveId)
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
    '   If Implementation: says [pending], replace with the real src/path:symbol.\n' +
    '   Scope paths (Creates: ∪ Modifies:):\n' + wave.allScope.join('\n') + '\n\n' +
    '4. LRN-100 relocation sweep: for every `*-budget-exhausted.md` file in\n' +
    '   `workspace/todos/deferred/` (including this wave\'s own, if any), check whether\n' +
    '   ALL findings in it are marked RESOLVED (no OPEN findings remain). If so, `mv` it to\n' +
    '   `workspace/todos/completed/` (same filename) — `deferred/` must only ever contain\n' +
    '   files with at least one OPEN finding. Leave files with any OPEN finding in place.\n\n' +
    'Report: file moved, plan.md updated (row updated or appended), FR fields updated,\n' +
    'and the list of any deferred markers relocated by the step-4 sweep (or none).',
    { label: 'archive', phase: 'Archive' }
  )

  // LRN-062 / RT-001: the archive agent's plan.md instructions above are not self-enforcing —
  // verify the row actually landed instead of trusting the report. On miss, self-heal with one
  // targeted append attempt; if that also fails, hard-block the wave as incomplete rather than
  // let it silently vanish from the ledger (the exact recurrence this guard exists to catch).
  const planRowCheck = await agent(
    'Run: grep -ci "' + wave.waveId + '" workspace/todos/plan.md\n' +
    'Report rowPresent: true if the count is >= 1, else false. Report the count as matchCount.',
    { schema: PLAN_ROW_SCHEMA, label: 'gate:archive-plan-row', phase: 'Archive' }
  )

  if (!planRowCheck || !planRowCheck.rowPresent) {
    log('WARNING: workspace/todos/plan.md has no row for ' + wave.waveId + ' after archive — self-healing (LRN-062 guard)')
    await agent(
      'workspace/todos/plan.md is missing a ledger row for wave ' + wave.waveId + ' even though it was ' +
      'just archived to workspace/todos/completed/ (or workspace/todos/archive/). Append this exact row ' +
      'to the end of the Wave summary table that this wave belongs to (the table with columns ' +
      'Wave | File | Parallel group | Slices | Depends):\n' +
      '`| ' + wave.waveId.toUpperCase() + ' [x] ✅ ' + TODAY + ' | ' + WAVE_FILE.replace('workspace/todos/', '') + ' | G | — | — |`\n' +
      'Do not modify or remove any other row.',
      { label: 'archive-plan-row-repair', phase: 'Archive' }
    )

    const planRowRecheck = await agent(
      'Run: grep -ci "' + wave.waveId + '" workspace/todos/plan.md\n' +
      'Report rowPresent: true if the count is >= 1, else false. Report the count as matchCount.',
      { schema: PLAN_ROW_SCHEMA, label: 'gate:archive-plan-row-recheck', phase: 'Archive' }
    )

    if (!planRowRecheck || !planRowRecheck.rowPresent) {
      archivePlanRowMissing = true
      log('BLOCKED — workspace/todos/plan.md still has no row for ' + wave.waveId + ' after repair attempt.')
      log('Archive is INCOMPLETE — add the row manually, then re-run /wave ' + wave.waveId + ' to confirm.')
    } else {
      log('plan.md row for ' + wave.waveId + ' appended by self-heal guard')
    }
  }

  log('Wave ' + wave.waveId + ' archived — ' + toCodeify.length + ' LRN(s) captured')
}

return {
  waveId:               wave.waveId,
  totalTodos:           totalTodos,
  lrnsCaptured:         toCodeify.length,
  cNnnRegistered:       registryCandidates.length,
  sdkCandidates:        sdkCandidatesCount,
  groupsExecuted:       wave.groups.length,
  phaseRedteamRounds:   pRound,
  exhausted:            pRound >= 8,
  protocolBlocked:      protocolBlocked,
  testsRed:             testsRed,
  testsBlockedArchive:  testsBlockedArchive,  // RT-003: distinguishes test-suite block from protocol block
  archivePlanRowMissing: archivePlanRowMissing,  // LRN-062 / RT-001: plan.md ledger row missing after self-heal
}
