export const meta = {
  name: 'wave-cycle',
  description: 'Execute one wave: todos plan redteam (SI annotations + registry reuse) → fan-out implement per group → unit zero-tolerance redteam (debug fires at round 4 (the only round above the fix-fan-out threshold before the round-5 deferred exit) or at any round when stall is detected; round 5 exits via deferred note) → phase zero-tolerance redteam (debug fires unconditionally at round 4+ (pRound > 3) and at any round when stall is detected; round 8 exits) → protocol audit → codify LRNs + register new C-NNN components → archive',
  phases: [
    { title: 'Parse',          detail: 'Read wave file; extract groups, creates paths, LRN baseline' },
    { title: 'Todos Redteam',  detail: 'Redteam the wave plan: SI risk annotation, registry reuse (Reuses: C-NNN), new component candidate flagging — annotated wave file written back before implement' },
    { title: 'Implement',      detail: 'Fan out todos per group in dependency order; smoke test each' },
    { title: 'Unit Redteam',   detail: 'Per-group zero-tolerance fix loop (max 5 rounds/group; debug fires at round 4 (the only round above the fix-fan-out threshold before the round-5 deferred exit) or at any round when stall is detected (same findings as previous round); round 5 exits via deferred note)' },
    { title: 'Phase Redteam',  detail: 'Full-wave zero-tolerance fix loop (max 8 rounds; debug fires unconditionally at round 4+ (pRound > 3) and at any round when stall is detected (same findings as previous round); round 8 exits)' },
    { title: 'Protocol Audit', detail: 'A2A/MCP/AG-UI/A2UI conformance — parallel advisors + seam check (protocol-surface waves only)' },
    { title: 'Codify',         detail: 'SDK issue scan (sequential) → parallel LRN capture for critical/high findings → README index update → sequential C-NNN registration for new component candidates' },
    { title: 'Archive',        detail: 'Move wave file to completed/, update plan.md, backfill FR Implementation: fields' },
  ],
}

// ─── args ─────────────────────────────────────────────────────────────────────
// args.waveFile : absolute path to the active wave file
// args.today    : ISO date string for plan.md timestamp (e.g. "2026-06-12")
// GH-131: the workflow sandbox bans the Date global outright, so the previous
// Date-based fallback for a missing args.today always threw when it fired — and it
// fired whenever args arrived JSON-encoded as a string (making args.today read as
// undefined through the object accessor), producing a Date-related crash with zero
// agents spawned instead of an error naming the actual missing arg. Normalize args
// first (string-encoded args are parsed; a missing/falsy args becomes {}), then fail
// fast naming whichever field(s) are absent — never fall back to Date.
// RT-017: GH-131's AC is to fail fast with a clear error naming the missing arg(s) — a
// string args payload that is not valid JSON must not still die with a bare, unattributed
// SyntaxError one layer up from the exact failure mode GH-131 removed.
let normalizedArgs
if (typeof args === 'string') {
  try {
    normalizedArgs = JSON.parse(args)
  } catch (e) {
    throw new Error(
      'wave-cycle: args arrived as a string but is not valid JSON — pass { waveFile, today } ' +
      '(or a JSON-encoded string of the same shape).'
    )
  }
} else {
  normalizedArgs = args || {}
}
const missingArgs = []
if (!normalizedArgs.waveFile) missingArgs.push('waveFile')
if (!normalizedArgs.today)    missingArgs.push('today')
if (missingArgs.length > 0) {
  throw new Error(
    'wave-cycle: missing required arg(s): ' + missingArgs.join(', ') +
    ' — pass { waveFile, today } (or a JSON-encoded string of the same shape).'
  )
}
const WAVE_FILE = normalizedArgs.waveFile
const TODAY     = normalizedArgs.today
// RT-004 (w036/w039 wave-ID collision): a reused wave ID whose basename already exists
// under workspace/todos/completed/ makes the archive step's `mv` (and the LRN-100
// deferred-marker relocation sweep) silently overwrite the earlier wave's record — no
// runner checked for this. WAVE_BASENAME anchors both the Parse-phase hard-block below
// and the archive-step anti-overwrite instruction to the same value.
const WAVE_BASENAME = WAVE_FILE.split('/').pop()

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
const AUTH_SURFACE = ['src/routes/oauth', 'src/auth/middleware', 'src/auth/oauth_tokens', 'src/auth/api_keys', 'src/auth/identity', 'src/auth/oidc']
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
  required: ['waveId', 'allCreates', 'allModifies', 'groups', 'groupDeps', 'lrnNext', 'completedFileExists'],
  additionalProperties: false,
  properties: {
    waveId:      { type: 'string' },
    allCreates:  { type: 'array', items: { type: 'string' }, description: 'RT-001 (fix round): every backticked path token a todo creates. A bare-path Creates: line is the MINORITY form in this repo\'s todos — the DOMINANT form declares every real path inside prose with no separate Modifies: field at all, e.g. `Creates: (modifies `a`, `b`, `c`); adds `x``, where `a`/`b`/`c` are modifies (see allModifies) and `x` alone is the create. Extraction must scan the whole Creates: line for every backticked token, not stop at the first one.' },
    allModifies: { type: 'array', items: { type: 'string' }, description: 'RT-001 (fix round): every backticked path token a todo modifies — both a dedicated Modifies: line AND every backticked token named inside a "modifies ..." clause (parenthetical or bare) on a Creates: line, which is how most of this repo\'s todos declare their real modify-set.' },
    lrnNext:     { type: 'integer' },
    completedFileExists: { type: 'boolean', description: 'RT-004: true if workspace/todos/completed/<basename of the wave file> already exists (`test -f workspace/todos/completed/<basename> && echo yes || echo no`), determined UNCONDITIONALLY while parsing — a reused wave ID whose basename collides with an already-archived wave would have its record silently overwritten by the archive step\'s mv-by-basename (and, for wave-cycle.js, the LRN-100 deferred-marker relocation sweep)' },
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

// RT-002 (w039 archival hygiene): two waves run concurrently against the same
// working tree with no isolation between them produce an uncommitted blob no
// single wave's history can be reviewed, reverted, or released independently
// of the other — the exact failure this schema's guard exists to catch before
// a SECOND wave's Implement phase starts stacking more uncommitted work on top.
const CONCURRENCY_GUARD_SCHEMA = {
  type: 'object',
  required: ['otherActiveWaves', 'dirtyPathCount'],
  additionalProperties: false,
  properties: {
    otherActiveWaves: {
      type: 'array',
      items: { type: 'string' },
      description: 'Basenames of other wave files (w[NNN]-*.md, excluding CHECKPOINT-*.md) ' +
        'in workspace/todos/active/ besides this run\'s own wave file',
    },
    dirtyPathCount: {
      type: 'integer',
      description: 'Number of lines from `git status --porcelain` at repo root (modified + ' +
        'staged + untracked paths, 0 if the working tree is clean)',
    },
  },
}

// RT-001 (w039/origin divergence): local `main` and `origin/main` can diverge silently —
// each ahead of the other with no fast-forward possible — and a wave will happily archive
// on top of that without ever noticing. See this schema's guard below, checked once right
// after Parse, alongside the concurrency guard.
const REMOTE_SYNC_SCHEMA = {
  type: 'object',
  required: ['behindCount'],
  additionalProperties: false,
  properties: {
    behindCount: {
      type: 'integer',
      description: 'Output of `git rev-list --count main..origin/main` after `git fetch ' +
        'origin main --quiet` (0 if origin/main is unreachable — no remote, no network — ' +
        'or already an ancestor of main)',
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
  required: ['issuesFound', 'reuseAnnotations', 'siAnnotations', 'sliceIssues', 'newCandidates', 'peerRepoAnnotations'],
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
    // RT-014 / LRN-085: a todo whose Creates:/Modifies: touches harness/workflows/*.js or
    // .claude/workflows/*.js but omits the template/.claude/workflows/<file>.js peer-repo
    // mirror (wailuen/a2a-agent-template) leaves propagation to out-of-band action — the
    // runtime copy /wave and the harness skill actually execute is never scoped as a wave
    // deliverable. See LRN-071 (template/ is a peer repo, not a submodule).
    peerRepoAnnotations: {
      type: 'array',
      items: {
        type: 'object',
        required: ['todoId', 'mirrorPath', 'note'],
        additionalProperties: false,
        properties: {
          todoId:     { type: 'string' },
          mirrorPath: { type: 'string' },
          note:       { type: 'string' },
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
// RT-008 (LRN-062/LRN-109 recurrence, compounded by RT-004 ID reuse): matching on wave.waveId
// alone passes vacuously once ANY wave sharing that id has a row — including a different wave
// that happens to reuse the same waveId, whose pre-existing row then silently satisfies this
// wave's own check. The check below now also requires the matched line to contain this wave's
// own File value (see waveFileTag at the archive-guard call site) so two waves sharing an id
// can no longer satisfy each other's ledger check.
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
// (tests/, docs/, workspace/learning/, workspace/scenarios/results/, workspace/prd/, .claude/workflows/,
// harness/workflows/, .claude/agents/, harness/agents/, .claude/skills/, harness/skills/) plus the
// single-file entry pyproject.toml (RT-007, below).
// Post-archive w035 follow-up: the workflow-file dirs were added after a
// GH-118 fix (RT-003, below) landed in wave-cycle.js without either wave.allScope or this dir
// list watching wave-cycle.js/sdk-wave.js's own directories — an undeclared workflow-file edit
// could evade offendingPaths (undeclared) AND offendingHarnessPaths (dir unwatched) at once.
// RT-007 (w036): the identical double-blind-spot recurred for harness agent/skill files — a
// todo touching .claude/agents/core/redteam.md, harness/agents/core/redteam.md, or
// .claude/skills/wave/SKILL.md was neither declared in any todo's Creates:/Modifies: (evading
// offendingPaths) nor watched by this dir list (evading offendingHarnessPaths) at once. Fix:
// .claude/agents/, harness/agents/, .claude/skills/, and harness/skills/ were added to the dir
// list above (and the matching schema description / prompt step 4 text below).
// RT-002 (round-7): template/.claude/workflows/ is the third byte-identical mirror (synced via
// test_workflow_sync.py). RT-001 (w036): that mirror lives inside a gitignored nested peer repo
// (template/), so it can NEVER show up in the top-level `git status --short` this gate runs in
// step 1 — watching it via the main-repo dirty-path list (step 4) was a dead guard. Step 4b
// separately runs `git -C template status --short` and folds any dirty .claude/workflows/ path
// from THAT output into offendingHarnessPaths (prefixed `template/`) — the only way this gate
// can see an uncommitted template mirror.
// RT-007 (pytest-gate blind spot): pyproject.toml sat outside every gate clause at once — not a
// harness dir (evading offendingHarnessPaths), not under agent_sdk/**.py or src/**.py (evading
// offendingUndeclaredScope), not a .py import target (evading offendingUndeclaredImports), and
// simply never named in a todo's Creates:/Modifies: (evading offendingPaths) — a sixth variant
// of the double-blind-spot class documented above. A pytest.ini_options edit (e.g. a
// filterwarnings entry broad enough to mask a genuine leaked event loop or socket) could land
// fully undetected by this gate. Fix: pyproject.toml was added to the dir list above as a
// single-file entry (and the matching schema description / prompt step 4 text below) — `starts
// with` matching degenerates to an exact match for a top-level file with no children.
// GH-118 (LRN-119): the checks above only catch paths git already sees as dirty/untracked
// AND either in wave.allScope or under a harness dir — they never inspect import statements.
// A module extracted mid-wave (agent_sdk/common/origin.py in GH-110 upstream; src/common/
// origin.py in this runner's downstream dialect) that sits untracked, is imported by a
// declared file, but is itself outside both allScope and the harness dirs produces no
// offending entry and silently passes the gate — risking an ImportError at boot on every
// importing surface if archive stages only declared paths. offendingUndeclaredImports
// closes that gap: it holds resolved intra-package import targets — absolute `src.*` in
// this runner's dialect, plus every relative form — of dirty/scope .py files that are
// themselves untracked and undeclared.
// RT-003: ported from sdk-wave.js — wave-cycle.js is the more widely-used wave runner and
// was left exposed to the LRN-119 failure class while sdk-wave.js alone carried the fix.
// RT-003 (w036, post-archive gh-issues review): a THIRD blind spot, orthogonal to the two
// above — a file that is TRACKED (already existed pre-wave, so offendingUndeclaredImports'
// `git ls-files` check never flags it), modified mid-wave, named only inside a todo's
// Reuses:/SI: prose annotation (never its own Creates:/Modifies: line, so it evades
// offendingPaths), and outside every harness deliverable dir (so it evades
// offendingHarnessPaths too). GH-135/GH-130 each hit this exact gap on tracked
// agent_sdk/**.py files (agent_sdk/routes/mcp.py, agent_sdk/routes/admin.py,
// agent_sdk/__init__.py, agent_sdk/common/redact.py) — in the a2a-sdk repo itself, where
// sdk-wave.js is the runner and agent_sdk/ is the source root. RT-003 (fix round): this
// check was ported into wave-cycle.js verbatim, including sdk-wave.js's agent_sdk/**.py
// glob — but wave-cycle.js's own dialect throughout this file (AUTH_SURFACE above,
// A2A_SURFACE/MCP_SURFACE/AGUI_SURFACE) addresses a downstream agent's source root as
// src/, never agent_sdk/ (the standard agent src/ tree ships neither src/auth/ nor
// src/routes/, let alone src/routes/mcp.py). An agent_sdk/**.py glob run against a
// downstream repo's src/ tree matches nothing, ever — offendingUndeclaredScope was a
// permanent no-op in every repo this runner actually executes in. offendingUndeclaredScope
// closes the gap for wave-cycle.js's real audience: any dirty, TRACKED src/**.py path
// absent from wave.allScope is flagged as undeclared scope drift and blocks archive, same
// as the other three checks. (sdk-wave.js keeps agent_sdk/**.py — that dialect is correct
// there, since agent_sdk/ is this SDK repo's own source root.)
// RT-004 (redteam finding on this wave; GH-131/GH-132/LRN-071/LRN-085): steps 4/4b and step 6
// above only ever detect a DIRTY template/.claude/workflows/ mirror — they say nothing when
// template/ is not checked out in this working tree at all. GH-131 and GH-132 both declared
// template/.claude/workflows/wave-cycle.js as a deliverable in Modifies:, yet template/ is a
// gitignored peer repo (LRN-071) that can be entirely absent from a checkout — in that case
// step 4b's own guard ("If a `template/` directory exists...") never fires, so this gate
// silently reports a clean archive-commit check even though the declared propagation was
// never verified. The two xfail(strict=True) guards in test_workflow_sync.py
// (test_wave_cycle_is_harness_template_shared, test_acceptance_api_is_harness_template_shared)
// keep that unverifiable state VISIBLE in the pytest summary, but visibility in a test report
// is not a propagation gate — xfail never fails the suite, so it never blocks archive here.
// templateDirExists below, plus the declaresTemplateScope hard-block after the archiveIntent
// response further down, close that gap: a wave that declares a template/ path as scope
// hard-blocks archive, loudly, whenever template/ is not checked out.
// RT-012 (post-archive gh-issues review): docs/content-types.md landed 64 net-new lines
// documenting the GH-130/RT-011 delimiter-safety contract with no todo declaring it in
// Creates:/Modifies: — invisible to offendingPaths (undeclared), offendingHarnessPaths (docs/
// was not a watched dir), offendingUndeclaredImports (not a .py file), AND
// offendingUndeclaredScope (not under src/**.py) simultaneously: a fifth variant of the
// same double-blind-spot RT-003/RT-007 closed for other file classes above. Fix: docs/ was
// added to the harness-deliverable dir list (HARNESS_DIRS in tests/test_workflows.py, and the
// matching schema description / prompt step 4 text below, in all three archive-gate runners).
const ARCHIVE_INTENT_SCHEMA = {
  type: 'object',
  required: ['gitStatusOutput', 'dirtyPaths', 'offendingPaths', 'offendingHarnessPaths', 'offendingUndeclaredImports', 'offendingUndeclaredScope', 'templateDirExists'],
  additionalProperties: false,
  properties: {
    gitStatusOutput:      { type: 'string', description: 'Raw stdout of git status --short' },
    dirtyPaths:           { type: 'array', items: { type: 'string' }, description: 'All paths reported dirty or untracked by git' },
    offendingPaths:       { type: 'array', items: { type: 'string' }, description: 'Dirty paths that overlap with wave.allScope (Creates: ∪ Modifies:)' },
    offendingHarnessPaths: { type: 'array', items: { type: 'string' }, description: 'Dirty/untracked paths under tests/, docs/, workspace/learning/, workspace/scenarios/results/, workspace/prd/, .claude/workflows/, harness/workflows/, .claude/agents/, harness/agents/, .claude/skills/, or harness/skills/, or exactly matching the single-file entry pyproject.toml (step 4) — plus, per step 4b, any dirty .claude/workflows/ path from `git -C template status --short` (the nested template repo), resolved to template/.claude/workflows/<file> — even if not in allScope' },
    offendingUndeclaredImports: { type: 'array', items: { type: 'string' }, description: 'GH-118/LRN-119/RT-001: resolved import targets (absolute src.* OR relative from ./from ..) of dirty/scope .py files that are untracked (git ls-files empty) AND absent from wave.allScope' },
    offendingUndeclaredScope: { type: 'array', items: { type: 'string' }, description: 'RT-003 (w036): dirty paths under src/**.py that ARE TRACKED (git ls-files returns them, unlike offendingUndeclaredImports which only inspects untracked .py files) but absent from wave.allScope — a source file modified mid-wave and named only in a todo\'s Reuses:/SI: prose, never added to Creates:/Modifies:. src/ is not a harness dir, so offendingHarnessPaths cannot see it either. RT-003 fix round: re-dialected from sdk-wave.js\'s agent_sdk/**.py to src/**.py, this runner\'s own dialect — see AUTH_SURFACE and the SOURCE-ROOT DIALECT note above ARCHIVE_INTENT_SCHEMA.' },
    templateDirExists:    { type: 'boolean', description: 'RT-004: true if a `template/` directory exists at the repo root (`test -d template`), determined UNCONDITIONALLY in step 0 below regardless of git status or tree cleanliness — the only signal this gate has for whether a wave that declares a template/ path in scope can have its propagation verified in this checkout' },
  },
}

// RT-005 (redteam finding on this wave; GH-131/GH-132/LRN-071/LRN-085, w036 deferred note):
// RT-004 above only discovers a missing template/ checkout at the ARCHIVE gate — after Todos
// Redteam, Implement, Unit Redteam, Phase Redteam, Protocol Audit, and Codify have all already
// run to completion and spent this wave's full agent-call budget on work that can never be
// archived. A minimal, single-purpose schema (deliberately NOT reusing ARCHIVE_INTENT_SCHEMA's
// full commit-check shape, which needs git status output this early check has no use for) lets
// the Parse-phase gate below ask the same `test -d template` question cheaply, before any of
// those expensive phases start.
const TEMPLATE_DIR_CHECK_SCHEMA = {
  type: 'object',
  required: ['templateDirExists'],
  additionalProperties: false,
  properties: {
    templateDirExists: { type: 'boolean', description: 'True if a `template/` directory exists at the repo root (`test -d template`)' },
  },
}

// RT-002 (redteam finding on .claude/skills/wave/SKILL.md wiring, GH-136 wave): every
// protocol-surface array above (AUTH_SURFACE, A2A_SURFACE, MCP_SURFACE, AGUI_SURFACE,
// A2UI_SURFACE) is hardcoded to src/-prefixed paths — the downstream-agent layout. Run against
// the a2a-sdk repo's own source tree, which lives under agent_sdk/ (no src/ at the repo root),
// every array evaluates false for every path this wave touches, so runProtocol is always false
// and the entire Protocol Audit phase is skipped with no log line naming the mismatch. The root
// cause was a self-contradictory instruction in .claude/skills/wave/SKILL.md (Mode A correctly
// launches sdk-wave.js — the agent_sdk/-prefixed runner — for this repo, but Mode B pointed back
// at wave-cycle.js); that doc bug is fixed separately. This schema backs the defensive code-level
// guard: wave-cycle.js itself must refuse to run against this layout rather than silently
// skipping protocol conformance. Mirrors TEMPLATE_DIR_CHECK_SCHEMA's shape — a minimal,
// single-purpose schema for a cheap `test`-only gate that runs before any expensive work starts.
const REPO_LAYOUT_CHECK_SCHEMA = {
  type: 'object',
  required: ['wrongRunnerForRepoLayout'],
  additionalProperties: false,
  properties: {
    wrongRunnerForRepoLayout: { type: 'boolean', description: 'True if the repo root has an agent_sdk/ directory but no src/ directory (`test -d agent_sdk && ! test -d src`) — the a2a-sdk repo\'s own layout, which this file\'s src/-prefixed protocol-surface arrays can never match' },
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

// GH-132: severity floor — only critical/high findings block the unit/phase redteam
// loops. Gating loop exit on raw findingsCount (every severity, including low) meant an
// adversarial reviewer's routine low-severity nit was enough to force the round cap every
// time — the round cap (5 unit / 8 phase) was effectively always hit. Medium/low findings
// are still surfaced (recorded once to a deferred note on every loop exit — RT-009, see
// accumulateNonBlocking below) but never themselves keep the loop going.
// RT-005 (round-7 fresh-lens debug): the two sets are COMPLEMENTS, and non-blocking is
// the one defined by an allow-list. Matching 'critical'/'high' here and 'medium'/'low'
// there left a third bucket that belonged to NEITHER set: a finding whose severity is
// absent, capitalised ('High'), or any other string did not block the loop, was not
// accumulated by accumulateNonBlocking(), and never reached the <wave>-medium-low.md
// deferred note — it vanished with no log line at all. That is the exact fail-OPEN this
// file rejects everywhere else (null agent responses, findingsCount mismatches —
// LRN-020/LRN-028/LRN-032). A finding is non-blocking ONLY when it says so; anything
// else blocks and is named in a warning so the odd severity is visible, not silent.
function isNonBlockingSeverity(f) {
  return f && (f.severity === 'medium' || f.severity === 'low')
}
function blockingFindings(findings) {
  return findings.filter(function(f) {
    if (isNonBlockingSeverity(f)) return false
    if (!f || f.severity !== 'critical' && f.severity !== 'high') {
      log('WARNING: finding ' + ((f && f.id) || '<no id>') + ' has unrecognised severity ' +
          JSON.stringify(f && f.severity) + ' — treating it as BLOCKING (fail-closed)')
    }
    return true
  })
}
function nonBlockingFindings(findings) {
  return findings.filter(isNonBlockingSeverity)
}

// RT-009: the clean-exit branch (blocking.length === 0) was the ONLY loop-exit path that
// wrote the medium/low deferred note — the null-gate break, findings-mismatch break, and
// tests-red break all exited the same while(true) loop with that round's non-blocking
// findings computed and then discarded. Every round now accumulates its nonBlockingFindings
// into a loop-scoped store (deduped by the same file+description key sigs() uses, so a
// finding resurfacing across rounds is recorded once, not once per round); the caller writes
// ONE deferred note from ONE place after the loop, regardless of which break fired.
function accumulateNonBlocking(store, seenSigs, findings) {
  for (const f of nonBlockingFindings(findings)) {
    const sig = f.file + ':' + f.description
    if (!seenSigs.has(sig)) {
      seenSigs.add(sig)
      store.push(f)
    }
  }
}

// GH-132: batch the fix fan-out into ONE agent per round covering every file, unless the
// round's blocking findings span more files than this threshold — a single prompt spanning
// too many files risks losing per-file fidelity, so past the threshold the loop falls back
// to the original one-agent-per-file parallel fan-out.
const FIX_BATCH_FILE_THRESHOLD = 6

// GH-132: hard cap on LRN files captured per wave. Findings beyond the cap were already
// fixed by the redteam loop above — only individual LRN codification is capped, so an
// unusually finding-heavy wave cannot fan out one parallel codify agent per finding with no
// ceiling.
const MAX_LRN_PER_WAVE = 20

// ─── agent-call budget (hard backstop) ────────────────────────────────────────
// GH-132: with the severity floor and debug-replaces-fix-fan-out changes above, steady-
// state agent-call volume per wave should collapse on its own — but as a backstop against
// any future or unforeseen runaway loop (e.g. a stalled loop, or an unusually wide finding
// set), every dispatched agent call is counted against a hard per-wave ceiling. Exceeding
// it stops the wave LOUDLY (throws) instead of silently continuing to spend agent calls.
// RT-002: overridable via args.agentBudget (the same Workflow(...) args object that carries
// waveFile/today) so a wave whose honest cost exceeds the default does not throw at the same
// point on every retry with no escape hatch short of editing this file. Number(...) so a
// JSON-encoded numeric string resolves correctly (normalizedArgs above already handles the
// string-encoded-args case).
// RT-006: a flat 150-call ceiling is documented (by this very comment, before this fix) as
// already below the honest cost of a routine 4-group wave (~4x20 unit-loop + ~32 phase + 24
// codify + implement + archive) — a hard backstop set below normal usage aborts waves that
// would otherwise complete, with no signal short of an operator already knowing to pass
// args.agentBudget. Recomputed below (see "AGENT_CALL_BUDGET recompute") once wave.groups.length
// is known, so the ceiling scales with the wave's own shape instead of a fixed constant; 150
// here is only the floor used for the handful of calls before Parse resolves the wave. An
// explicit args.agentBudget of exactly 0 is invalid (silently falling back to a default via
// `0 || default` would hide a typo'd override), so it is rejected below rather than tolerated.
// RT-015: an exact-zero override is not the only invalid shape — Number('abc') is NaN, not 0,
// so a typo'd override would sail past a zero-only check, and the very next line's
// `Number(x) || default` pattern would then silently swallow the NaN into the default too (NaN
// is falsy, same as 0). Validate the full contract ONCE, here: any provided override must be a
// finite, positive number — this single guard covers exactly-zero (0 fails `> 0`), negative,
// non-finite, and non-numeric overrides alike. RT-011 (fix round): a dedicated exact-zero guard
// used to run before this one and throw for the same 0 input — fully redundant, since this
// guard already rejects 0 (0 is not > 0) and JSON.stringify(0) still renders unquoted "0", so
// the thrown message reads identically for a 0 override either way. Only undefined/null
// (omitted — use the default) and an override that survives this check can ever reach the
// `|| default` line below, so that fallback can only fire for "omitted", never for "invalid".
if (normalizedArgs.agentBudget !== undefined && normalizedArgs.agentBudget !== null &&
    !(Number.isFinite(Number(normalizedArgs.agentBudget)) && Number(normalizedArgs.agentBudget) > 0)) {
  throw new Error(
    'wave-cycle: agentBudget must be a positive number if provided (got ' +
    JSON.stringify(normalizedArgs.agentBudget) + ') — omit it entirely to use the default, or ' +
    'pass a real ceiling.'
  )
}
let AGENT_CALL_BUDGET = Number(normalizedArgs.agentBudget) || 150
let agentCallCount = 0
// RT-012: tracked so the budget-exceeded deferred note (below) can record where in the
// wave the ceiling was hit — the last successfully dispatched call, since the one that
// trips the budget check never itself dispatches. waveIdForBudgetNote starts as a WAVE_FILE
// fallback because a budget of 1 (pathological but not impossible) could trip on the very
// first call, before the Parse phase has resolved wave.waveId.
let lastDispatchedLabel = 'none'
let lastDispatchedPhase = 'Parse'
let waveIdForBudgetNote = WAVE_FILE
const _dispatchAgent = agent
async function callAgent(prompt, opts) {
  agentCallCount++
  if (agentCallCount > AGENT_CALL_BUDGET) {
    log('BUDGET EXCEEDED: ' + agentCallCount + ' agent call(s) dispatched this wave — hard budget is ' +
        AGENT_CALL_BUDGET + '. Stopping loudly to prevent runaway cost; investigate the loop or ' +
        'finding volume that drove this before re-running.')
    // WC-003: write a deferred note so the operator has a durable artifact indicating why
    // the wave stopped and how to retry — every other terminal exit path in this file does
    // this; the budget throw did not (RT-012). Dispatched through the raw _dispatchAgent
    // (bypassing callAgent) so the note write itself cannot be blocked by the very budget
    // it exists to report on.
    await _dispatchAgent(
      'Write workspace/todos/deferred/' + waveIdForBudgetNote + '-agent-budget-exceeded.md\n\n' +
      'Include: waveId (' + waveIdForBudgetNote + '), wave file (' + WAVE_FILE + '), date (' +
      TODAY + '), agentCallCount (' + agentCallCount + '), hard budget (' + AGENT_CALL_BUDGET +
      '), last phase dispatched (' + lastDispatchedPhase + '), last label dispatched (' +
      lastDispatchedLabel + '), reason: agent-call budget exceeded mid-wave.\n' +
      'Instruction: "This budget is overridable — a bare /wave ' + waveIdForBudgetNote +
      ' retry will hit the same ' + AGENT_CALL_BUDGET + '-call ceiling at the same point ' +
      'every time. Investigate the loop or finding volume that drove this, THEN re-run with ' +
      'a higher ceiling by passing agentBudget in the workflow args (args.agentBudget on the ' +
      'Workflow(...) call that launches wave-cycle.js), e.g. args: { waveFile, today, ' +
      'agentBudget: 300 }."',
      { label: 'defer:agent-budget-exceeded', phase: lastDispatchedPhase }
    )
    throw new Error('agent-call budget exceeded (' + AGENT_CALL_BUDGET + ' calls) for this wave')
  }
  lastDispatchedLabel = (opts && opts.label) || lastDispatchedLabel
  lastDispatchedPhase = (opts && opts.phase) || lastDispatchedPhase
  return _dispatchAgent(prompt, opts)
}

// ─── state ────────────────────────────────────────────────────────────────────
let registryCandidates = []   // new C-NNN candidates from Todos Redteam → registered in Codify

// ─── phase 0: parse wave file ─────────────────────────────────────────────────
phase('Parse')

// RT-002: repo-layout check runs first, before the wave file is even read — it depends only on
// the checkout's own directory layout, not on wave content, so the wrong-runner case fails fast
// instead of burning a parse call (and everything after it) on a wave that can never get a
// Protocol Audit. Fail-closed (RT-001/WC-001 convention used throughout this file): a null
// response is unknown state, treated the same as a confirmed wrong-runner layout.
const repoLayoutCheck = await callAgent(
  'Run `test -d agent_sdk && ! test -d src && echo yes || echo no` at the repo root and report the result.',
  { schema: REPO_LAYOUT_CHECK_SCHEMA, label: 'gate:repo-layout-check', phase: 'Parse' }
)
if (!repoLayoutCheck || repoLayoutCheck.wrongRunnerForRepoLayout) {
  log('ABORT — this repo root has an agent_sdk/ package and no src/ directory: wave-cycle.js is ' +
      'the wrong runner here. Its protocol-surface arrays (AUTH_SURFACE, A2A_SURFACE, ' +
      'MCP_SURFACE, AGUI_SURFACE, A2UI_SURFACE) are hardcoded to src/-prefixed paths and can ' +
      'never match agent_sdk/ — every wave run this way silently skips the entire Protocol ' +
      'Audit phase. Use sdk-wave.js instead: .claude/skills/wave/SKILL.md launches it for this ' +
      'repo (Mode A step 2 and Mode B step 3).')
  return { error: 'wrong-runner-for-repo-layout' }
}

const wave = await callAgent(
  'Read the wave file at: ' + WAVE_FILE + '\n\n' +
  'Also read workspace/learning/README.md to find the highest LRN number ' +
  '(e.g. LRN-023 → lrnNext = 24; if none, lrnNext = 1).\n\n' +
  'Extract:\n' +
  '- waveId: the w[NNN] identifier from the filename\n' +
  '- A "path token" is a backticked token that names exactly ONE FILE. RT-001\n' +
  '  (round-7 fresh-lens debug): these lines are PROSE, so they also backtick things\n' +
  '  that are NOT scope. REJECT every one of the following outright: a DIRECTORY (any\n' +
  '  token ending in "/" — `agent_sdk/`, `docs/`, `.claude/agents/`, `harness/skills/`),\n' +
  '  a GLOB (any token containing "*" or "?" — `agent_sdk/**.py`, `tests/test_*.py`), a\n' +
  '  slash-command (`/sdk-test`), an identifier or dotted attribute chain\n' +
  '  (`max_retries`, `wave.allScope`, `openai.RateLimitError`), and a bare extension\n' +
  '  (`.py`). A directory or glob token is NEVER wave scope even when the prose plainly\n' +
  '  mentions it — e.g. an aside reading "(`agent_sdk/` is not a harness dir)" declares\n' +
  '  NOTHING. Each scope entry is a claim about one deliverable and the archive gate\n' +
  '  reads it as one, so a single directory token would declare an entire subtree and\n' +
  '  silently disable the undeclared-scope check. Accept a token only if its FINAL\n' +
  '  segment is a filename ending in a real repo extension (.py .js .ts .md .json .toml\n' +
  '  .yaml .yml): `harness/wave_scope.py`, `pyproject.toml`, and\n' +
  '  `.claude/workflows/wave-cycle.js` all qualify (a leading dot-segment is fine — the\n' +
  '  FINAL segment is what must look like a filename). RT-001 (residual fix): a token\n' +
  '  with NO "/" at all is further restricted to ROOT-LEVEL extensions (.md .json\n' +
  '  .toml .yaml .yml) — no .py/.js/.ts source file is ever bare at this repo\'s root,\n' +
  '  every real one is nested, so a bare `wave-cycle.js` or `test_workflow_sync.py`\n' +
  '  can never string-match the real, directory-qualified dirty path `git status`\n' +
  '  reports for it and must be REJECTED; write the full path instead. This rule is\n' +
  '  the prose twin of harness/wave_scope.py::_looks_like_path; keep the two in step.\n' +
  '- allCreates: every backticked repo-relative path token this wave creates. RT-001\n' +
  '  (fix round): a "Creates:" line is NOT always a bare path — this repo\'s dominant\n' +
  '  todo form puts every real deliverable inside prose with NO separate "Modifies:"\n' +
  '  field at all, e.g. a todo line reading: Creates: (modifies `a`, `b`, `c`); adds\n' +
  '  `d`, `e`. Scan the FULL "Creates:" line for EVERY backticked path token, wherever\n' +
  '  it sits — inside a parenthetical "(modifies ...)" clause, after a trailing "adds\n' +
  '  ..." / "adds/updates ..." clause, or bare. NEVER stop at the first backticked\n' +
  '  token on the line: a Creates: line naming six modified files inside one\n' +
  '  parenthetical, followed by a trailing "adds `x`" clause, has SEVEN real paths, not\n' +
  '  one. A path token belongs in allCreates UNLESS it sits inside a "modifies ..."\n' +
  '  clause (parenthetical or bare) naming it — those belong in allModifies instead.\n' +
  '- allModifies: every backticked repo-relative path token this wave modifies. This\n' +
  '  includes BOTH a dedicated "Modifies:" line\'s paths AND every backticked path\n' +
  '  token named inside a "modifies ..." clause on a Creates: line, parenthetical or\n' +
  '  bare — e.g. Creates: (modifies `a`); modifies `b` names TWO modifies, not one. Do\n' +
  '  NOT assume a todo\'s real modify-set appears only on its own "Modifies:" line: most\n' +
  '  todos in this repo declare it entirely inside Creates: prose instead.\n' +
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
  '- completedFileExists: run `test -f workspace/todos/completed/' + WAVE_BASENAME +
  ' && echo yes || echo no` UNCONDITIONALLY (regardless of anything else above) and set ' +
  'completedFileExists to true/false accordingly.\n\n' +
  'Return structured data.',
  { schema: WAVE_SCHEMA, label: 'parse', phase: 'Parse' }
)

if (!wave) {
  log('ERROR: could not parse wave file at ' + WAVE_FILE)
  return { error: 'parse-failed' }
}
// RT-004 (w036/w039 wave-ID collision): hard-block BEFORE any other Parse-phase work when
// this wave's basename already exists in workspace/todos/completed/ — proceeding would let
// the archive step (and, for wave-cycle.js, the LRN-100 deferred-marker relocation sweep)
// silently overwrite the earlier wave's record via mv-by-basename. Fail fast and name the
// fix instead of discovering the collision only at archive time.
if (wave.completedFileExists) {
  log('ERROR: wave ID collision — workspace/todos/completed/' + WAVE_BASENAME + ' already ' +
      'exists. Archiving ' + WAVE_FILE + ' under this ID would overwrite the earlier wave\'s ' +
      'record. Rename this wave file (and any workspace/todos/deferred/' +
      (wave.waveId || '<waveId>') + '-*.md markers) to an unused wave ID, then re-run.')
  return { error: 'wave-id-collision', waveId: wave.waveId, completedFile: 'workspace/todos/completed/' + WAVE_BASENAME }
}
// RT-012: now that wave.waveId is known, the budget-exceeded deferred note (if the ceiling
// is ever hit later in this run) can name it precisely instead of falling back to WAVE_FILE.
waveIdForBudgetNote = wave.waveId

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

// RT-006 (AGENT_CALL_BUDGET recompute): now that wave.groups.length is known, widen the hard
// backstop to track the wave's own shape rather than the flat constant used for the handful of
// Parse-phase calls above. An explicit args.agentBudget override always wins (kept as the upper
// hand, per RT-002); otherwise the floor scales with group count so a normal-sized wave's honest
// cost — the exact volume the pre-fix 150 constant was documented as falling below — no longer
// trips the same backstop meant to catch runaway loops, not routine usage.
AGENT_CALL_BUDGET = Number(normalizedArgs.agentBudget) || Math.max(150, 45 * wave.groups.length + 80)

if (wave.allScope.length === 0) {
  log('ERROR: wave ' + wave.waveId + ' has no Creates: AND no Modifies: paths — aborting ' +
      '(truly empty scope is a harness bug, not a clean wave)')
  return { error: 'empty-scope', waveId: wave.waveId }
}

// RT-005 (redteam finding on this wave; GH-131/GH-132/LRN-071/LRN-085, w036 deferred note):
// a wave that declares a template/ peer-repo deliverable in Creates:/Modifies: but runs from
// a checkout where template/ (wailuen/a2a-agent-template) was never cloned cannot have that
// deliverable land — no amount of Implement/Redteam/Codify work changes that. Discovering
// this only at the RT-004 archive gate below means every one of those phases already ran and
// spent the wave's agent-call budget on work whose declared propagation was never landable.
// Fail fast here instead, before any of them start. TEMPLATE_DIR_CHECK_SCHEMA (not
// ARCHIVE_INTENT_SCHEMA) keeps this check to the one fact it needs.
const parseDeclaresTemplateScope = wave.allScope.some(function(p) { return p.startsWith('template/') })
if (parseDeclaresTemplateScope) {
  const templateCheck = await callAgent(
    'Run `test -d template && echo yes || echo no` at the repo root and report the result.',
    { schema: TEMPLATE_DIR_CHECK_SCHEMA, label: 'gate:template-dir-check', phase: 'Parse' }
  )
  // Fail-closed (RT-001/WC-001 convention used throughout this file): a null response means
  // unknown state, which is not the same as template/ being present.
  if (!templateCheck || templateCheck.templateDirExists === false) {
    log('ABORT — wave ' + wave.waveId + ' declares a template/ deliverable but template/ is not checked out in this working tree:')
    wave.allScope.filter(function(p) { return p.startsWith('template/') })
      .forEach(function(p) { log('  [template/ absent] ' + p) })
    log('Clone the peer repo (wailuen/a2a-agent-template, LRN-071) into template/ at the repo root, ' +
        'copy the declared file(s) in from their harness/workflows/ source, verify `diff` is empty, ' +
        'then `git -C template/ commit && git -C template/ push`. Re-run /wave ' + wave.waveId +
        ' once template/ is checked out and the propagation can be verified.')
    return { error: 'template-dir-missing', waveId: wave.waveId }
  }
}

// RT-002 (w039 archival hygiene): a second wave starting its Implement phase while an
// EARLIER wave's file still sits in workspace/todos/active/ AND the working tree is
// uncommitted stacks that earlier wave's uncommitted work underneath this run's own —
// by the time either archives, neither can be committed, reviewed, or reverted as an
// independent unit (the two wave's changes end up interleaved in the same diff with no
// isolation). This was previously only a comment (WC-RT-005) noting the risk without
// enforcing it. Checked once, right after Parse, before any file mutation this run
// might make — a wave RESUMING itself (its own file already in active/) is not blocked,
// only a genuinely OTHER wave file coexisting with dirty state.
const concurrency = await callAgent(
  'List every wave file directly inside workspace/todos/active/ that matches the ' +
  'pattern w[0-9]+-*.md, EXCLUDING CHECKPOINT-*.md files and excluding the file at ' +
  WAVE_FILE + ' itself (this run\'s own wave file — do not report it even if its ' +
  'basename matches). Return their basenames as otherActiveWaves (empty array if none).\n\n' +
  'Separately, run `git status --porcelain` at the repo root and return the number of ' +
  'lines it prints as dirtyPathCount (0 if the working tree is clean).',
  { schema: CONCURRENCY_GUARD_SCHEMA, label: 'concurrency-guard', phase: 'Parse' }
)

if (concurrency && concurrency.otherActiveWaves.length > 0 && concurrency.dirtyPathCount > 0) {
  log('ERROR: wave ' + wave.waveId + ' cannot start — ' +
      concurrency.otherActiveWaves.join(', ') + ' already sits in workspace/todos/active/ ' +
      'and the working tree has ' + concurrency.dirtyPathCount + ' uncommitted path(s). ' +
      'Commit or archive the other wave first (or re-run this wave from a dedicated ' +
      'worktree) — running two waves against one uncommitted tree produces a diff neither ' +
      'can be reviewed, reverted, or released independently of the other.')
  return {
    error: 'concurrent-wave-uncommitted',
    waveId: wave.waveId,
    otherActiveWaves: concurrency.otherActiveWaves,
    dirtyPathCount: concurrency.dirtyPathCount,
  }
}

// RT-001 (w039/origin divergence): w039 landed and archived on a local `main` that was,
// unnoticed, simultaneously 5 commits ahead AND 14 commits behind `origin/main` — v0.6.0
// and v0.7.0 were already tagged upstream and unmerged into this history, and every one of
// w039's own scope files had also changed upstream in the gap. A wave "landed" on a branch
// that cannot be shipped without a later merge is not landed. Checked once, right after
// Parse — same point as the concurrency guard above — so a diverged branch is caught before
// Implement does any work that later has to be reconciled against an upstream nobody looked
// at. Fetch failure (no `origin` remote, no network) degrades to behindCount 0 rather than
// blocking every wave in an offline or remoteless repo.
const remoteSync = await callAgent(
  'Run `git fetch origin main --quiet` at the repo root (ignore failure — no configured ' +
  '`origin` remote or no network access both mean this check does not apply). Then run ' +
  '`git rev-list --count main..origin/main` and return the printed integer as behindCount ' +
  '(0 if that command fails for any reason, e.g. no such remote or no such branch).',
  { schema: REMOTE_SYNC_SCHEMA, label: 'remote-sync-guard', phase: 'Parse' }
)

if (remoteSync && remoteSync.behindCount > 0) {
  log('ERROR: wave ' + wave.waveId + ' cannot start — local main is ' +
      remoteSync.behindCount + ' commit(s) behind origin/main. Fetch and merge or rebase ' +
      'onto origin/main first, run the full suite + mypy on the merged tree, and ' +
      're-verify this wave\'s acceptance criteria against the post-merge code before ' +
      'Implement — work landed on a diverged branch is not landed.')
  return {
    error: 'behind-origin',
    waveId: wave.waveId,
    behindCount: remoteSync.behindCount,
  }
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
let   templatePropagationBlocked = false  // RT-004: archive blocked because this wave declares a template/ deliverable but template/ is not checked out (GH-131/GH-132/LRN-071/LRN-085)
let   unitBudgetBlocked   = false    // RT-004 (this wave): a group's unit redteam loop exited on the round-5 budget cap with surviving critical/high findings — archive must not proceed as if clean
let   phaseBudgetBlocked  = false    // RT-003 (this wave): the phase redteam loop exited on the round-8 budget cap with surviving critical/high findings — archive must not proceed as if clean
let   redteamUnknownBlocked = false  // RT-003 (this wave, LRN-032): a redteam round budget was exhausted while the verdict was never established (persistent null response, or a findingsCount/findings mismatch) — distinct from unitBudgetBlocked/phaseBudgetBlocked, which fire only once real findings survived; archive must not proceed on an UNKNOWN verdict either
let   totalTodos       = 0
let   sdkCandidatesCount = 0   // set by sdk:scan in Codify phase

// ─── phase 1: todos redteam ───────────────────────────────────────────────────
phase('Todos Redteam')

const planRt = await callAgent(
  'Review the todo plan for wave ' + wave.waveId + ' BEFORE implementation starts.\n\n' +
  'Wave file: ' + WAVE_FILE + '\n' +
  'Also read:\n' +
  '  - workspace/components/README.md  (C-NNN registry)\n' +
  '  - workspace/learning/README.md    (past learnings + Prevention clauses)\n' +
  '  - .claude/reference/sdk-security-invariants.md  (SI-1…SI-7)\n\n' +
  'Check ONLY these five things (do not re-audit cross-wave ordering):\n' +
  '1. REGISTRY REUSE — does a C-NNN component already cover this todo\'s capability?\n' +
  '   If yes, add to reuseAnnotations. Implementers will use the annotation to\n' +
  '   reuse the component rather than rebuild it.\n' +
  '2. SI RISK — does this todo\'s Creates: path touch SI-1..SI-7 territory?\n' +
  '   If yes and SI: field is absent, add to siAnnotations.\n' +
  '3. VERTICAL SLICE — is this todo a horizontal layer instead of an end-to-end\n' +
  '   deliverable? Add to sliceIssues only if genuinely non-vertical.\n' +
  '4. NEW COMPONENT CANDIDATES — would any planned code be reusable across\n' +
  '   multiple agents or waves? Add name/location/description to newCandidates.\n' +
  '5. PEER-REPO PROPAGATION (LRN-085/RT-014) — does this todo\'s Creates:/Modifies:\n' +
  '   list include `.claude/workflows/<file>.js` or `harness/workflows/<file>.js`\n' +
  '   WITHOUT also including `template/.claude/workflows/<file>.js`? That path is a\n' +
  '   THIRD byte-identical mirror living in the peer repo wailuen/a2a-agent-template —\n' +
  '   the runtime copy downstream agents actually execute — and propagation to it is\n' +
  '   never implicit (see LRN-071). If a todo touches the first two without the third,\n' +
  '   add {todoId, mirrorPath: "template/.claude/workflows/<file>.js", note} to\n' +
  '   peerRepoAnnotations.\n\n' +
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
    const hasAnnotations = (planRt.reuseAnnotations     && planRt.reuseAnnotations.length > 0) ||
                           (planRt.siAnnotations         && planRt.siAnnotations.length > 0) ||
                           (planRt.peerRepoAnnotations   && planRt.peerRepoAnnotations.length > 0)
    const hasSliceIssues = planRt.sliceIssues && planRt.sliceIssues.length > 0

    if (hasSliceIssues) {
      log('Todos Redteam: ' + planRt.sliceIssues.length + ' slice issue(s) — logged (not blocking)')
      planRt.sliceIssues.forEach(function(s) { log('  [slice] ' + s.todoId + ': ' + s.issue) })
    }

    if (registryCandidates.length > 0) {
      log('Todos Redteam: ' + registryCandidates.length + ' new component candidate(s) flagged')
    }

    if (planRt.peerRepoAnnotations && planRt.peerRepoAnnotations.length > 0) {
      log('Todos Redteam: ' + planRt.peerRepoAnnotations.length + ' peer-repo propagation gap(s) flagged (LRN-085)')
    }

    if (hasAnnotations) {
      log('Todos Redteam: writing SI, registry, and peer-repo annotations back to wave file before implement')
      await callAgent(
        'Annotate the wave file ' + WAVE_FILE + ' with these additions.\n\n' +
        'Registry reuse (add `Reuses: <componentId>` to the matching todo body):\n' +
        JSON.stringify(planRt.reuseAnnotations, null, 2) + '\n\n' +
        'SI risk (add `SI: <siId>  # <note>` to the matching todo body):\n' +
        JSON.stringify(planRt.siAnnotations, null, 2) + '\n\n' +
        'Peer-repo propagation (LRN-085/RT-014) — append `mirrorPath` to the matching\n' +
        'todo\'s `Creates:` (or `Modifies:`) list, with the annotation:\n' +
        '"lands via commit+push to wailuen/a2a-agent-template per LRN-071; runtime\n' +
        'copy is what /acceptance / the harness skill actually executes — implementer\n' +
        'runs `git -C template/ commit && git -C template/ push` as an explicit\n' +
        'final step":\n' +
        JSON.stringify(planRt.peerRepoAnnotations, null, 2) + '\n\n' +
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
    await callAgent(
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
        return callAgent(
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
            return callAgent(
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

// Groups are partitioned by non-overlapping file scope (the planner groups conflicting
// todos together — the same guarantee Implement relies on to run a tier concurrently), so
// every group's review → diagnose → fix loop is independent and all groups run at once.
// The one shared resource is the pytest gate: it reads the WHOLE repo, so a gate running
// while a neighbouring group's fix agents are mid-edit could grade a transient state and
// misattribute the failure (LRN-017: the gate's exitCode is the sole authoritative signal —
// it must never be uncertain about what it graded). The mutate-and-verify section of each
// round (debug → fix → gate → fix-tests → re-gate) is therefore serialised across groups by
// gateLock; the read-only rt review call stays outside the lock so group B can review while
// group A fixes-and-gates. A stale review read of a neighbour's file mid-edit is the same
// self-correcting risk Implement already accepts — it yields a finding that is re-checked
// next round, never a wrong gate verdict.
let gateLock = Promise.resolve()
function withGateLock(fn) {
  const run = gateLock.then(fn, fn)                        // run after the queue ahead of it, whatever its outcome
  gateLock = run.then(function() {}, function() {})      // keep the chain alive even if fn throws
  return run
}

// Disjointness guard: the concurrent path is only safe while no two groups share a scope
// path. Two scope paths collide when equal, or when one is a directory prefix of the other.
// If the planner invariant does not hold for this wave, warn and fall back to the
// one-group-at-a-time order (gateLock is then uncontended and behaves as a pass-through).
function scopePathsOverlap(a, b) {
  if (a === b) return true
  const aDir = a.charAt(a.length - 1) === '/' ? a : a + '/'
  const bDir = b.charAt(b.length - 1) === '/' ? b : b + '/'
  return b.indexOf(aDir) === 0 || a.indexOf(bDir) === 0
}
const scopeOverlaps = []
wave.groups.forEach(function(a, ai) {
  wave.groups.slice(ai + 1).forEach(function(b) {
    const shared = a.scope.filter(function(p) {
      return b.scope.some(function(q) { return scopePathsOverlap(p, q) })
    })
    if (shared.length > 0) scopeOverlaps.push({ a: a.label, b: b.label, shared: shared })
  })
})

// Resolves to { label, rounds } on every normal exit so the fan-out below can tell a
// finished group from one whose thunk threw (parallel() maps a throw to null).
const runUnitRedteamForGroup = async function(group) {
  log('Unit redteam — group ' + group.label)
  let uRound       = 0
  let prevSigs     = new Set()
  // RT-009: accumulates every round's non-blocking findings, across ALL loop-exit paths —
  // written once, after the loop, regardless of which break fired.
  let groupNonBlocking = []
  let groupNonBlockingSigs = new Set()

  while (true) {
    uRound++

    const rt = await callAgent(
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
        await callAgent(
          'Write workspace/todos/deferred/' + wave.waveId + '-group-' + group.label + '-rt-null-budget.md\n\n' +
          'Include: wave ID (' + wave.waveId + '), group (' + group.label + '), date (' + TODAY + '),\n' +
          'round (' + uRound + '), reason: unit redteam agent returned null on every round — unknown state.\n' +
          'Instruction: "Re-run /wave ' + wave.waveId + ' to retry unit redteam for this group."',
          { label: 'defer:unit:' + group.label + ':rt-null-budget', phase: 'Unit Redteam' }
        )
        // RT-003 (this wave, LRN-032): an UNKNOWN verdict (persistent null response) must
        // block archive at least as hard as one where findings actually survived — writing a
        // deferred note without setting a blocking flag was fail-open, the exact
        // LRN-019/LRN-023/LRN-028/LRN-030 class. redteamUnknownBlocked (not
        // unitBudgetBlocked) so the archive-skip message names the real cause.
        protocolBlocked = true
        redteamUnknownBlocked = true
        break
      }
      // Do NOT reset prevSigs — preserve the last real finding set so stall detection
      // fires correctly on the next round if findings have not changed.
      continue
    }

    // RT-016: a single invariant replaces the old two-special-case guard (findingsCount===0
    // with a non-empty array; findingsCount>0 with an empty array) — either special case left a
    // PARTIAL mismatch (e.g. findingsCount=5, findings=[<1 item>]) passing both checks untouched
    // while `blocking` (derived from rt.findings only) silently dropped the other 4 findings,
    // letting the loop break clean on the severity floor. Any inequality between findingsCount
    // and the actual array length is unknown state — fail closed exactly like a null response,
    // with the same round-budget/deferred-note handling; never self-heal by overwriting
    // findingsCount, since a partial mismatch cannot be trusted enough to correct in place.
    if (rt.findingsCount !== rt.findings.length) {
      log('WARNING: findingsCount=' + rt.findingsCount + ' does not match findings array length ' +
          rt.findings.length + ' for group ' + group.label + ' round ' + uRound +
          ' — treating as unknown (not clean); preserving last known sig set')
      if (uRound >= 5) {
        log('Findings-count mismatch exceeded round budget for group ' + group.label + ' — deferring')
        await callAgent(
          'Write workspace/todos/deferred/' + wave.waveId + '-group-' + group.label + '-rt-mismatch-budget.md\n\n' +
          'Include: wave ID (' + wave.waveId + '), group (' + group.label + '), date (' + TODAY + '),\n' +
          'round (' + uRound + '), reason: unit redteam agent reported findingsCount=' + rt.findingsCount +
          ' but findings array has ' + rt.findings.length + ' item(s) — unknown state on every round.\n' +
          'Instruction: "Re-run /wave ' + wave.waveId + ' to retry unit redteam for this group."',
          { label: 'defer:unit:' + group.label + ':rt-mismatch-budget', phase: 'Unit Redteam' }
        )
        // RT-003 (this wave, LRN-032): this exit is NEW in this wave and fails closed exactly
        // like the null-response branch above — which itself was fail-open before this fix.
        // A findingsCount/findings mismatch on every round is an UNKNOWN verdict, not a clean
        // one; it must block archive the same way, via redteamUnknownBlocked.
        protocolBlocked = true
        redteamUnknownBlocked = true
        break
      }
      // Do NOT reset prevSigs — preserve the last real finding set so stall detection
      // fires correctly on the next round if findings have not changed.
      continue
    }

    // GH-132: severity floor — only critical/high findings block the loop. Gating on raw
    // findingsCount (every severity) meant a routine low-severity nit alone forced the round
    // cap every time. RT-009: medium/low findings are accumulated (deduped) into
    // groupNonBlocking every round and written to ONE deferred note after the loop ends —
    // on every exit path, not only when the loop happens to exit clean.
    const blocking = blockingFindings(rt.findings)
    const nonBlocking = nonBlockingFindings(rt.findings)
    accumulateNonBlocking(groupNonBlocking, groupNonBlockingSigs, rt.findings)

    if (blocking.length === 0) {
      log('Group ' + group.label + ' clean at round ' + uRound + ' (no critical/high findings)' +
          (nonBlocking.length > 0 ? '; ' + nonBlocking.length + ' medium/low finding(s) deferred' : ''))
      break
    }

    log('Group ' + group.label + ' round ' + uRound + ': ' + blocking.length + ' blocking finding(s)' +
        (nonBlocking.length > 0 ? ' (+' + nonBlocking.length + ' medium/low, non-blocking)' : ''))

    const curSigs = sigs(blocking)
    const stalled = uRound > 1 && sigsEqual(curSigs, prevSigs)

    // RT-004: codify accumulation MUST happen before the round-budget exit below (and every
    // other exit path from here on) — GH-132's severity floor means reaching the round cap now
    // signals SURVIVING critical/high findings, not a leftover low nit, so they must reach the
    // Codify LRN pass / SDK-issue scan even when the loop is about to give up on this group.
    // RT-011: do NOT filter on f.codify — a critical/high finding whose redteam output omitted
    // the required "Codify:" line was being dropped from allHighFindings entirely, so it never
    // reached the Codify LRN pass NOR the SDK issue scan (both iterate this same set). Warn by
    // id so a missing Codify: line stays visible; the codify agent already receives the
    // finding's full description/fix (see the LRN-write prompt in phase 6 below) and can
    // synthesise a lesson from those when codify itself is absent.
    const missingCodify = blocking.filter(function(f) { return !f.codify })
    if (missingCodify.length > 0) {
      log('WARNING: ' + missingCodify.length + ' critical/high finding(s) in group ' + group.label +
          ' missing a Codify: line: ' + missingCodify.map(function(f) { return f.id }).join(', '))
    }
    const highFindings = blocking
    allHighFindings.push.apply(allHighFindings, highFindings)

    // Deferred-exit check before debug — avoids wasting a debug agent call that's immediately
    // abandoned. RT-004: also marks the wave as blocked — reaching this cap means critical/high
    // findings survived every fix attempt, so the wave must not archive as if clean.
    if (uRound >= 5) {
      log('Round budget exhausted for group ' + group.label + ' — deferring and blocking archive (surviving critical/high findings)')
      await callAgent(
        'Write workspace/todos/deferred/' + wave.waveId + '-group-' + group.label + '-budget-exhausted.md\n\n' +
        'Include: wave ID (' + wave.waveId + '), group (' + group.label + '), date (' + TODAY + '),\n' +
        'round count (' + uRound + '), and the final findings:\n' +
        JSON.stringify(rt.findings, null, 2) + '\n\n' +
        'Instruction in the file: "Fix remaining findings, then re-run /wave ' + wave.waveId + '".',
        { label: 'defer:unit:' + group.label, phase: 'Unit Redteam' }
      )
      unitBudgetBlocked = true
      protocolBlocked = true
      break
    }

    // Mutate-and-verify critical section — serialised across groups by gateLock (see the
    // phase preamble). Resolves true when this round hit a loop-exit path (null gate, or
    // re-gate still red after the test-fix) so the caller breaks out of the round loop.
    const exitLoop = await withGateLock(async function() {
      // RT-006 / GH-132: debug REPLACES the fix fan-out (rather than running alongside it) at
      // round 4+ (uRound > 3) or on stall — the debug agent already fixes at the root itself
      // (see its prompt below), so also dispatching the per-file/batched fix fan-out in the same
      // round duplicated the fix work and compounded agent cost. Round 5 exits via deferred note
      // above.
      const escalateToDebug = uRound > 3 || stalled
      if (escalateToDebug) {
        log((stalled ? 'Stall detected — ' : 'Round 4+ — ') + 'escalating to debug agent (replaces fix fan-out this round)')
        await callAgent(
          'Fix-loop requires fresh-lens analysis' + (stalled ? ' (stalled: same findings across 2 rounds)' : ' (round ' + uRound + ')') + '.\n\n' +
          'Prior findings:\n' + JSON.stringify(blocking, null, 2) + '\n\n' +
          'Scope:\n' + group.scope.join('\n') + '\n\n' +
          'Read code cold. Diagnose root cause. Fix at the root.',
          { label: 'debug:unit:' + group.label + ':r' + uRound, phase: 'Unit Redteam', agentType: 'debug' }
        )
      }
      prevSigs = curSigs

      if (!escalateToDebug) {
        // GH-132: batch into ONE agent covering every file this round unless the round's
        // blocking findings span more files than FIX_BATCH_FILE_THRESHOLD — past that, fall
        // back to the original one-agent-per-file parallel fan-out.
        const byFile = {}
        for (const f of blocking) {
          if (!byFile[f.file]) byFile[f.file] = []
          byFile[f.file].push(f)
        }
        const files = Object.keys(byFile)

        const fixTasks = files.length > FIX_BATCH_FILE_THRESHOLD
          ? files.map(function(file) {
              return function() {
                return callAgent(
                  'Fix these findings in ' + file + ':\n\n' +
                  JSON.stringify(byFile[file], null, 2) + '\n\n' +
                  'Enforce SDK SI-1…SI-7 in your fix. Run pytest -q after.',
                  { label: 'fix:unit:' + group.label + ':r' + uRound + ':' + file.replace(/\//g, '-'),
                    phase: 'Unit Redteam', agentType: 'python-implementer' }
                )
              }
            })
          : [function() {
              return callAgent(
                'Fix these findings, grouped by file:\n\n' +
                JSON.stringify(byFile, null, 2) + '\n\n' +
                'Enforce SDK SI-1…SI-7 in your fixes. Run pytest -q after.',
                { label: 'fix:unit:' + group.label + ':r' + uRound, phase: 'Unit Redteam', agentType: 'python-implementer' }
              )
            }]

        await parallel(fixTasks)
      }

      // GH-19: consume gate result — red suite blocks loop continuation.
      // RT-001: fail-closed — null gate response is unknown state, treated as failure.
      const unitGate = await callAgent(
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
        await callAgent(
          'Write workspace/todos/deferred/' + wave.waveId + '-group-' + group.label + '-gate-null-r' + uRound + '.md\n\n' +
          'Include: wave ID (' + wave.waveId + '), group (' + group.label + '), date (' + TODAY + '),\n' +
          'round (' + uRound + '), reason: unit gate agent returned null (unknown test state).\n' +
          'Instruction: "Re-run /wave ' + wave.waveId + ' to retry gate for this group."',
          { label: 'defer:unit:' + group.label + ':gate-null:r' + uRound, phase: 'Unit Redteam' }
        )
        // RT-002: null gate blocks loop continuation — do not silently proceed.
        return true
      }
      if (unitGate.exitCode !== 0) {
        testsRed = true
        log('Gate RED (' + unitGate.failCount + ' failing) — dispatching test-fix agent')
        await callAgent(
          'Fix the failing tests below. Read the test file and the source it covers.\n' +
          'Failing tests:\n' + unitGate.failures.join('\n') + '\n\n' +
          'Run `python -m pytest -q <failing-test-file>` to confirm GREEN before finishing.',
          { label: 'fix:tests:unit:' + group.label + ':r' + uRound, phase: 'Unit Redteam' }
        )
        // RT-002: re-gate after test-fix to verify the fix succeeded before continuing the loop.
        const unitReGate = await callAgent(
          'Run: python -m pytest -q\n' +
          'Report: exitCode (0=pass, non-zero=fail), passCount, failCount, and failures (list of\n' +
          '"test_file.py::test_name: reason" strings for each failing test). Return all fields.',
          { schema: GATE_SCHEMA, label: 'gate:unit:' + group.label + ':r' + uRound + ':recheck', phase: 'Unit Redteam' }
        )
        // RT-001: fail-closed — null re-gate is still unknown, treat as red.
        if (!unitReGate || unitReGate.exitCode !== 0) {
          const failCount = unitReGate ? unitReGate.failCount : '?'
          log('Re-gate still RED (' + failCount + ' failing) after test-fix — deferring group ' + group.label)
          await callAgent(
            'Write workspace/todos/deferred/' + wave.waveId + '-group-' + group.label + '-tests-red-r' + uRound + '.md\n\n' +
            'Include: wave ID (' + wave.waveId + '), group (' + group.label + '), date (' + TODAY + '),\n' +
            'round (' + uRound + '), reason: test suite RED after fix attempt.\n' +
            'Instruction: "Fix failing tests and re-run /wave ' + wave.waveId + '".',
            { label: 'defer:unit:' + group.label + ':tests-red:r' + uRound, phase: 'Unit Redteam' }
          )
          return true
        }
      }
      return false
    })
    if (exitLoop) break
  }

  // RT-009: written ONCE, after the loop, from ONE place — covers every exit path (clean,
  // null-round budget, findings-mismatch budget, round-budget-exhausted, null-gate,
  // tests-red), not only the clean-exit branch that used to write this inline.
  if (groupNonBlocking.length > 0) {
    await callAgent(
      'Write workspace/todos/deferred/' + wave.waveId + '-group-' + group.label + '-medium-low.md\n\n' +
      'Include: wave ID (' + wave.waveId + '), group (' + group.label + '), date (' + TODAY + '),\n' +
      'non-blocking (medium/low) findings accumulated across every unit redteam round for this ' +
      'group (deduped by file+description):\n' +
      JSON.stringify(groupNonBlocking, null, 2) + '\n\n' +
      'Instruction in the file: "Non-blocking — these did not block ' + wave.waveId + '\'s archive. ' +
      'Address opportunistically or fold into a future wave."',
      { label: 'defer:unit:' + group.label + ':medium-low', phase: 'Unit Redteam' }
    )
  }
  return { label: group.label, rounds: uRound }
}

if (scopeOverlaps.length > 0) {
  scopeOverlaps.forEach(function(o) {
    log('WARNING: groups ' + o.a + ' and ' + o.b + ' share scope path(s): ' + o.shared.join(', '))
  })
  log('Scope overlap detected — planner disjointness invariant violated; running Unit Redteam ' +
      'one group at a time for this wave (concurrent path skipped)')
  for (const group of wave.groups) {
    await runUnitRedteamForGroup(group)
  }
} else {
  if (wave.groups.length > 1) {
    log('Unit redteam — ' + wave.groups.length + ' groups concurrently (fix + gate serialised): ' +
        wave.groups.map(function(g) { return g.label }).join(', '))
  }
  const unitResults = await parallel(wave.groups.map(function(group) {
    return function() { return runUnitRedteamForGroup(group) }
  }))
  // parallel() resolves a thrown thunk to null instead of rejecting — surface it so a group
  // whose round loop aborted mid-way is not mistaken for a clean exit. Fail closed: an
  // aborted group never established a verdict, so archive must not proceed as if clean.
  // A budget-exceeded throw inside a group thunk is also mapped to null by parallel() —
  // re-raise it here so the hard backstop still stops the wave loudly.
  if (agentCallCount > AGENT_CALL_BUDGET) {
    throw new Error('agent-call budget exceeded (' + AGENT_CALL_BUDGET + ' calls) for this wave')
  }
  unitResults.forEach(function(r, i) {
    if (!r) {
      log('WARNING: unit redteam for group ' + wave.groups[i].label + ' aborted with an error before a clean exit — not clean; re-run /wave ' + wave.waveId)
      protocolBlocked = true
      redteamUnknownBlocked = true
    }
  })
}

// ─── phase 4: phase redteam (whole wave, zero-tolerance) ─────────────────────
phase('Phase Redteam')

let pRound   = 0
let prevSigs = new Set()
// RT-009: accumulates every round's non-blocking findings, across ALL loop-exit paths —
// written once, after the loop, regardless of which break fired.
let phaseNonBlocking = []
let phaseNonBlockingSigs = new Set()

// LRN-136: Phase Redteam reviews wave.allScope — the UNION of every group's scope. On a
// single-group wave that union IS the one group's scope, which Unit Redteam has just
// zero-tolerance-cleared with the same review dimensions, the same debug escalation
// (round 4+ / stall) and the same fix → gate machinery. A second pass over the same files
// adds no coverage — there is no second group, so no cross-group interaction surface —
// while adding up to 8 more rounds of dispatches. Multi-group waves MUST still run it:
// only a whole-wave pass can catch e.g. group A changing a signature that group B's
// already-reviewed code calls. Skipping leaves every downstream variable in the state a
// clean pass would (pRound stays 0) — nothing after this block special-cases it.
if (wave.groups.length === 1) {
  log('Phase Redteam skipped — single-group wave (' + wave.groups[0].label + '): Unit Redteam already reviewed this exact scope ' +
      'with the same review dimensions; no cross-group interaction surface exists.')
} else {
  while (true) {
    pRound++

    const rt = await callAgent(
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
        await callAgent(
          'Write workspace/todos/deferred/' + wave.waveId + '-phase-rt-null-budget.md\n\n' +
          'Include: wave ID (' + wave.waveId + '), date (' + TODAY + '),\n' +
          'round (' + pRound + '), reason: phase redteam agent returned null on every round — unknown state.\n' +
          'Instruction: "Re-run /wave ' + wave.waveId + ' to retry phase redteam."',
          { label: 'defer:phase:rt-null-budget', phase: 'Phase Redteam' }
        )
        // RT-003 (this wave, LRN-032): mirrors the unit loop's null-response budget fix —
        // an UNKNOWN verdict must block archive at least as hard as one where findings
        // actually survived. redteamUnknownBlocked (not phaseBudgetBlocked) so the
        // archive-skip message names the real cause.
        protocolBlocked = true
        redteamUnknownBlocked = true
        break
      }
      // RT-004: do NOT reset prevSigs — preserve the last real finding set so stall detection
      // fires correctly on the next round if findings have not changed. Resetting prevSigs here
      // would defeat stall detection: a null round followed by a round with the same findings as
      // the prior real round would not trigger sigsEqual because prevSigs was cleared.
      // continue to next round — do not fall through to fix/debug logic; prevSigs not reset so stall detection remains valid
      continue
    }

    // RT-016: a single invariant replaces the old two-special-case guard — see the matching
    // unit-loop comment above for the PARTIAL-mismatch gap this closes. Any inequality between
    // findingsCount and the actual array length is unknown state — fail closed exactly like a
    // null response, with the same round-budget/deferred-note handling; never self-heal by
    // overwriting findingsCount, since a partial mismatch cannot be trusted enough to correct.
    if (rt.findingsCount !== rt.findings.length) {
      log('WARNING: findingsCount=' + rt.findingsCount + ' does not match findings array length ' +
          rt.findings.length + ' at round ' + pRound + ' — treating as unknown (not clean)')
      if (pRound >= 8) {
        log('Findings-count mismatch exceeded phase round budget — deferring')
        await callAgent(
          'Write workspace/todos/deferred/' + wave.waveId + '-phase-rt-mismatch-budget.md\n\n' +
          'Include: wave ID (' + wave.waveId + '), date (' + TODAY + '),\n' +
          'round (' + pRound + '), reason: phase redteam agent reported findingsCount=' + rt.findingsCount +
          ' but findings array has ' + rt.findings.length + ' item(s) — unknown state on every round.\n' +
          'Instruction: "Re-run /wave ' + wave.waveId + ' to retry phase redteam."',
          { label: 'defer:phase:rt-mismatch-budget', phase: 'Phase Redteam' }
        )
        // RT-003 (this wave, LRN-032): this exit is NEW in this wave and fails closed exactly
        // like the null-response branch above. A findingsCount/findings mismatch on every
        // round is an UNKNOWN verdict; block archive via redteamUnknownBlocked.
        protocolBlocked = true
        redteamUnknownBlocked = true
        break
      }
      // Do NOT reset prevSigs — preserve the last real finding set so stall detection fires
      // correctly on the next round if findings have not changed.
      continue
    }

    // GH-132: severity floor — only critical/high findings block the loop. RT-009: medium/low
    // findings are accumulated (deduped) into phaseNonBlocking every round and written to ONE
    // deferred note after the loop ends — on every exit path, not only clean exit.
    const blocking = blockingFindings(rt.findings)
    const nonBlocking = nonBlockingFindings(rt.findings)
    accumulateNonBlocking(phaseNonBlocking, phaseNonBlockingSigs, rt.findings)

    if (blocking.length === 0) {
      log('Phase redteam clean at round ' + pRound + ' (no critical/high findings)' +
          (nonBlocking.length > 0 ? '; ' + nonBlocking.length + ' medium/low finding(s) deferred' : ''))
      break
    }

    log('Phase redteam round ' + pRound + ': ' + blocking.length + ' blocking finding(s)' +
        (nonBlocking.length > 0 ? ' (+' + nonBlocking.length + ' medium/low, non-blocking)' : ''))

    const curSigs = sigs(blocking)
    const pStalled = pRound > 1 && sigsEqual(curSigs, prevSigs)

    // RT-003: codify accumulation MUST happen before the round-budget exit below (and every other
    // exit path from here on) — GH-132's severity floor means reaching the round cap now signals
    // SURVIVING critical/high findings, not a leftover low nit, so they must reach the Codify LRN
    // pass / SDK-issue scan even when the loop is about to give up on the whole wave.
    // RT-011: do NOT filter on f.codify — same reasoning as the unit loop above: a critical/high
    // finding missing the required "Codify:" line must not silently vanish from the Codify LRN
    // pass AND the SDK issue scan. Warn by id; the codify agent synthesises from description/fix
    // (it already receives the full finding JSON) when codify itself is absent.
    const missingCodify = blocking.filter(function(f) { return !f.codify })
    if (missingCodify.length > 0) {
      log('WARNING: ' + missingCodify.length + ' critical/high finding(s) missing a Codify: line: ' +
          missingCodify.map(function(f) { return f.id }).join(', '))
    }
    const highFindings = blocking
    allHighFindings.push.apply(allHighFindings, highFindings)

    // Budget-exit check before debug — avoids wasting a debug agent call that's immediately
    // abandoned. RT-003: also marks the wave as blocked and writes a deferred note (mirroring the
    // unit loop's round-budget exit) — reaching this cap means critical/high findings survived
    // every fix attempt across the whole wave, so it must not archive as if clean.
    if (pRound >= 8) {
      log('Phase round budget exhausted — deferring and blocking archive (surviving critical/high findings)')
      await callAgent(
        'Write workspace/todos/deferred/' + wave.waveId + '-phase-budget-exhausted.md\n\n' +
        'Include: wave ID (' + wave.waveId + '), date (' + TODAY + '),\n' +
        'round count (' + pRound + '), and the final findings:\n' +
        JSON.stringify(rt.findings, null, 2) + '\n\n' +
        'Instruction in the file: "Fix remaining findings, then re-run /wave ' + wave.waveId + '".',
        { label: 'defer:phase:budget-exhausted', phase: 'Phase Redteam' }
      )
      phaseBudgetBlocked = true
      protocolBlocked = true
      break
    }

    // RT-006 / GH-132: debug REPLACES the fix fan-out (rather than running alongside it) at
    // round 4+ (pRound > 3) or on stall — the debug agent already fixes at the root itself, so
    // also dispatching the per-file/batched fix fan-out in the same round duplicated the fix
    // work and compounded agent cost. Round 8 exits above.
    const pEscalateToDebug = pRound > 3 || pStalled
    if (pEscalateToDebug) {
      log((pStalled ? 'Stall detected — ' : 'Round 4+ — ') + 'escalating to debug agent (replaces fix fan-out this round)')
      await callAgent(
        'Phase fix-loop requires fresh-lens analysis' + (pStalled ? ' (stalled)' : ' (round ' + pRound + ')') + '.\n\n' +
        'Findings:\n' + JSON.stringify(blocking, null, 2) + '\n\n' +
        'Scope:\n' + wave.allScope.join('\n') + '\n\n' +
        'Read cold; diagnose; fix at root.',
        { label: 'debug:phase:r' + pRound, phase: 'Phase Redteam', agentType: 'debug' }
      )
    }
    prevSigs = curSigs

    if (!pEscalateToDebug) {
      // GH-132: batch into ONE agent covering every file this round unless the round's blocking
      // findings span more files than FIX_BATCH_FILE_THRESHOLD — past that, fall back to the
      // original one-agent-per-file parallel fan-out.
      const byFile = {}
      for (const f of blocking) {
        if (!byFile[f.file]) byFile[f.file] = []
        byFile[f.file].push(f)
      }
      const files = Object.keys(byFile)

      const fixTasks = files.length > FIX_BATCH_FILE_THRESHOLD
        ? files.map(function(file) {
            return function() {
              return callAgent(
                'Fix findings in ' + file + ':\n\n' + JSON.stringify(byFile[file], null, 2) + '\n\n' +
                'Enforce SI-1…SI-7. Run pytest -q after.',
                { label: 'fix:phase:r' + pRound + ':' + file.replace(/\//g, '-'),
                  phase: 'Phase Redteam', agentType: 'python-implementer' }
              )
            }
          })
        : [function() {
            return callAgent(
              'Fix findings, grouped by file:\n\n' + JSON.stringify(byFile, null, 2) + '\n\n' +
              'Enforce SI-1…SI-7. Run pytest -q after.',
              { label: 'fix:phase:r' + pRound, phase: 'Phase Redteam', agentType: 'python-implementer' }
            )
          }]

      await parallel(fixTasks)
    }

    // GH-19: consume gate result — red suite blocks loop continuation.
    // RT-001: fail-closed — null gate response is unknown state, treated as failure.
    const phaseGate = await callAgent(
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
      await callAgent(
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
      await callAgent(
        'Fix the failing tests below. Read the test file and the source it covers.\n' +
        'Failing tests:\n' + phaseGate.failures.join('\n') + '\n\n' +
        'Run `python -m pytest -q <failing-test-file>` to confirm GREEN before finishing.',
        { label: 'fix:tests:phase:r' + pRound, phase: 'Phase Redteam' }
      )
      // RT-002: re-gate after test-fix to verify the fix succeeded before continuing the loop.
      const phaseReGate = await callAgent(
        'Run: python -m pytest -q\n' +
        'Report: exitCode (0=pass, non-zero=fail), passCount, failCount, and failures (list of\n' +
        '"test_file.py::test_name: reason" strings for each failing test). Return all fields.',
        { schema: GATE_SCHEMA, label: 'gate:phase:r' + pRound + ':recheck', phase: 'Phase Redteam' }
      )
      // RT-001: fail-closed — null re-gate is still unknown, treat as red and stop the loop.
      if (!phaseReGate || phaseReGate.exitCode !== 0) {
        const failCount = phaseReGate ? phaseReGate.failCount : '?'
        log('Re-gate still RED (' + failCount + ' failing) after test-fix — stopping phase redteam loop')
        await callAgent(
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
}

// RT-009: written ONCE, after the loop, from ONE place — covers every exit path (clean,
// null-round budget, findings-mismatch budget, round-budget-exhausted, null-gate, tests-red),
// not only the clean-exit branch that used to write this inline.
if (phaseNonBlocking.length > 0) {
  await callAgent(
    'Write workspace/todos/deferred/' + wave.waveId + '-phase-medium-low.md\n\n' +
    'Include: wave ID (' + wave.waveId + '), date (' + TODAY + '),\n' +
    'non-blocking (medium/low) findings accumulated across every phase redteam round ' +
    '(deduped by file+description):\n' +
    JSON.stringify(phaseNonBlocking, null, 2) + '\n\n' +
    'Instruction in the file: "Non-blocking — these did not block ' + wave.waveId + '\'s archive. ' +
    'Address opportunistically or fold into a future wave."',
    { label: 'defer:phase:medium-low', phase: 'Phase Redteam' }
  )
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
      return callAgent(
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
      return callAgent(
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
      return callAgent(
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
      return callAgent(
        'A2UI v0.9.1 + Standard Profile v1.1 conformance audit.\n\n' +
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
    return callAgent(
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

  // RT-001 (round-6 fresh-lens): fail-closed on a null advisor result. This fan-out was the
  // ONLY agent-result consumer in this file that did not guard `if (!x) { ...blocked }` —
  // `(await parallel(advisorTasks)).filter(Boolean)` silently DISCARDED a crashed or
  // schema-rejected advisor, so an a2a/mcp/ag-ui/a2ui/seam leg that never produced a verdict
  // contributed 0 to protoCritical/protoHigh, protocolBlocked stayed false, and the wave
  // archived as protocol-clean without having been audited on that protocol at all. A dropped
  // verdict is UNKNOWN, never clean (LRN-019/022/023/024/026/029/030/031/063). Null results are
  // counted before they are filtered, and the count blocks archive.
  const rawProtoResults  = await parallel(advisorTasks)
  const nullAdvisorCount = rawProtoResults.filter(function(r) { return !r }).length
  if (nullAdvisorCount > 0) {
    log('WARNING: ' + nullAdvisorCount + ' protocol advisor(s) returned null — treating as ' +
        'unknown (not clean); archive BLOCKED')
    protocolBlocked = true
  }
  const protoResults = rawProtoResults.filter(Boolean)
  let protoCritical = protoResults.reduce(function(n, r) { return n + (r.criticalCount || 0) }, 0)
  const protoHigh   = protoResults.reduce(function(n, r) { return n + (r.highCount || 0) }, 0)
  const allProtoFindings = protoResults.reduce(function(acc, r) {
    return acc.concat(r.findings || [])
  }, [])

  log('Protocol audit: ' + protoCritical + ' critical, ' + protoHigh + ' high')

  // RT-011: same fix as the unit/phase redteam loops above — do not require f.codify to reach
  // allHighFindings. A protocol-audit critical/high finding missing a Codify: line must still
  // reach the Codify LRN pass and SDK issue scan, not vanish silently.
  const protoBlocking = allProtoFindings.filter(function(f) {
    return f.severity === 'critical' || f.severity === 'high'
  })
  const missingCodifyProto = protoBlocking.filter(function(f) { return !f.codify })
  if (missingCodifyProto.length > 0) {
    log('WARNING: ' + missingCodifyProto.length + ' critical/high protocol finding(s) missing a ' +
        'Codify: line: ' + missingCodifyProto.map(function(f) { return f.protocol + ':' + f.rule }).join(', '))
  }
  allHighFindings.push.apply(allHighFindings,
    protoBlocking.map(function(f) {
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
    await callAgent(
      'Fix ALL critical protocol conformance findings below. These block archive.\n\n' +
      'Findings:\n' + JSON.stringify(
        allProtoFindings.filter(function(f) { return f.severity === 'critical' }),
        null, 2
      ) + '\n\n' +
      'Run pytest -q after fixing. Report files changed.',
      { label: 'proto:fix', phase: 'Protocol Audit', agentType: 'python-implementer' }
    )

    // GH-20: gate after protocol fix — domain regressions must be caught before recheck
    const protoFixGate = await callAgent(
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
      await callAgent(
        'Fix the failing tests introduced by the protocol fix. Read the test file and source.\n' +
        'Failing tests:\n' + protoFixGate.failures.join('\n') + '\n\n' +
        'Run `python -m pytest -q <failing-test-file>` to confirm GREEN before finishing.',
        { label: 'fix:tests:proto:fix', phase: 'Protocol Audit' }
      )
      // WC-RT-002: re-gate after proto test-fix — unit and phase loops each have a formal
      // re-gate (unitReGate/phaseReGate); the proto path must too. A failed test-fix that
      // silently proceeds to the recheck (and then to archive) defeats zero-tolerance.
      const protoTestReGate = await callAgent(
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
        await callAgent(
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
        return callAgent(
          'A2A v0.3.0 re-audit after preceding fix. Check same surfaces.\n' +
          'Scope paths (Creates: ∪ Modifies:):\n' + wave.allScope.join('\n') + '\n' +
          'Focus on previously-critical findings. Return structured findings.',
          { schema: PROTO_SCHEMA, agentType: 'a2a-advisor', label: 'proto:recheck:a2a', phase: 'Protocol Audit' }
        )
      })
    }
    if (runMCP) {
      recheckTasks.push(function() {
        return callAgent(
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
        return callAgent(
          'AG-UI re-audit after preceding fix.\n' +
          'Scope paths (Creates: ∪ Modifies:):\n' + wave.allScope.join('\n') + '\n' +
          'Focus on previously-critical findings. Return structured findings.',
          { schema: PROTO_SCHEMA, agentType: 'ag-ui-advisor', label: 'proto:recheck:agui', phase: 'Protocol Audit' }
        )
      })
    }
    if (runA2UI) {
      recheckTasks.push(function() {
        return callAgent(
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
      return callAgent(
        'Cross-protocol seam re-audit after preceding fix.\n' +
        'Candidate route/shared surfaces in scope:\n' +
        (seamPaths.length > 0 ? seamPaths.join('\n') : '(none matched by name — shared/auth surface change; see full scope below)') + '\n' +
        'Scope paths (Creates: ∪ Modifies:):\n' + wave.allScope.join('\n') + '\n' +
        'Focus on previously-critical SEAM findings. Return structured findings.',
        { schema: PROTO_SCHEMA, label: 'proto:recheck:seam', phase: 'Protocol Audit' }
      )
    })
    // RT-001 (round-6 fresh-lens): fail-closed, same as the initial fan-out above. A null
    // recheck advisor here is strictly worse than at initial dispatch — it drops the verdict
    // on a protocol that ALREADY had a critical finding, so `protoCritical` recomputes to 0
    // and the wave archives as though the fix were verified.
    const rawRecheckResults = await parallel(recheckTasks)
    const nullRecheckCount  = rawRecheckResults.filter(function(r) { return !r }).length
    if (nullRecheckCount > 0) {
      log('WARNING: ' + nullRecheckCount + ' protocol recheck advisor(s) returned null — ' +
          'previously-critical protocol left unverified; archive BLOCKED')
      protocolBlocked = true
    }
    const recheckResults = rawRecheckResults.filter(Boolean)
    protoCritical = recheckResults.reduce(function(n, r) { return n + (r.criticalCount || 0) }, 0)

    if (protoCritical > 0) {
      log('BLOCKED — critical protocol findings persist; wave will not archive')
      protocolBlocked = true
      await callAgent(
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

// GH-132: hard cap on LRN files captured per wave (MAX_LRN_PER_WAVE, defined above). Findings
// beyond the cap were already fixed by the redteam loop — only individual LRN codification is
// capped, so an unusually finding-heavy wave cannot fan out one parallel codify agent per
// finding with no ceiling. The SDK issue scan below still classifies the FULL toCodeify set.
const lrnCandidates = toCodeify.slice(0, MAX_LRN_PER_WAVE)
if (toCodeify.length > MAX_LRN_PER_WAVE) {
  const overflowLrnCandidates = toCodeify.slice(MAX_LRN_PER_WAVE)
  log('WARNING: ' + toCodeify.length + ' critical/high finding(s) — capping LRN capture at ' +
      MAX_LRN_PER_WAVE + ' per wave (' + overflowLrnCandidates.length +
      ' finding(s) already fixed but not individually codified)')
  // RT-018: every other truncation/budget path in this file writes a deferred note (the
  // AGENT_CALL_BUDGET throw does, per RT-012, on the stated rationale that every other terminal
  // exit path in this file does) — this cap dropped findings past MAX_LRN_PER_WAVE with only a
  // transient log() line, losing them permanently instead of leaving a durable artifact.
  await callAgent(
    'Write workspace/todos/deferred/' + wave.waveId + '-lrn-cap-exceeded.md\n\n' +
    'Include: wave ID (' + wave.waveId + '), date (' + TODAY + '), MAX_LRN_PER_WAVE (' +
    MAX_LRN_PER_WAVE + '), and the ' + overflowLrnCandidates.length + ' finding(s) that exceeded ' +
    'the per-wave LRN capture cap (already fixed by the redteam loop, but not individually ' +
    'codified as LRN files):\n' +
    JSON.stringify(overflowLrnCandidates, null, 2) + '\n\n' +
    'Instruction in the file: "These findings were already fixed but not codified as LRN files ' +
    'due to the ' + MAX_LRN_PER_WAVE + '-per-wave cap. Review and codify opportunistically, or ' +
    'fold into a future wave."',
    { label: 'defer:codify:lrn-cap-exceeded', phase: 'Codify' }
  )
}

log('Codifying ' + lrnCandidates.length + ' critical/high finding(s)' +
    (toCodeify.length > MAX_LRN_PER_WAVE ? ' (of ' + toCodeify.length + ' total)' : ''))

// ─── SDK issue scan (sequential, before LRN capture) ─────────────────────────
// Classify critical/high findings as SDK-level vs agent-domain.
// SDK-level ones are written to workspace/sdk-candidates.md for /sdk-issue-scan.
if (toCodeify.length > 0) {
  const sdkScan = await callAgent(
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

    await callAgent(
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

if (lrnCandidates.length > 0) {
  // LRN writes are batched ~LRN_BATCH_SIZE findings per codify agent (one dispatch writes
  // N files) instead of one agent per finding — each agent pays full spin-up to write one
  // small file, so a wide per-finding fan-out is mostly overhead. Numbering is unchanged:
  // every finding carries lrnBase + its ORIGINAL index in lrnCandidates, computed before
  // batching, so an ID never depends on batch position. Batches still run concurrently.
  const LRN_BATCH_SIZE = 5
  const lrnAssignments = lrnCandidates.map(function(f, i) {
    const lrnNum = lrnBase + i
    return { lrnId: 'LRN-' + String(lrnNum).padStart(3, '0'), finding: f }
  })
  const lrnBatches = []
  for (let start = 0; start < lrnAssignments.length; start += LRN_BATCH_SIZE) {
    lrnBatches.push(lrnAssignments.slice(start, start + LRN_BATCH_SIZE))
  }
  log('Writing ' + lrnAssignments.length + ' LRN file(s) in ' + lrnBatches.length + ' batch(es) of up to ' + LRN_BATCH_SIZE)

  await parallel(lrnBatches.map(function(batch) {
    return function() {
      const ids = batch.map(function(a) { return a.lrnId })
      const entries = batch.map(function(a, k) {
        const f     = a.finding
        const lrnId = a.lrnId
        return '### Learning file ' + (k + 1) + ' of ' + batch.length + ' — ' + lrnId + '\n' +
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
          'Keep the file under 1KB.'
      }).join('\n\n')
      return callAgent(
        'Write ' + batch.length + ' learning file(s) — one file per entry below, each with its own\n' +
        'Write call, using exactly the Assigned ID and File path given for that entry.\n' +
        'Do NOT touch workspace/learning/README.md yet.\n\n' +
        entries,
        { label: 'codify:' + ids[0] + (ids.length > 1 ? '..' + ids[ids.length - 1] : ''),
          phase: 'Codify', agentType: 'codify' }
      )
    }
  }))

  await callAgent(
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
  await callAgent(
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
const preArchiveGate = await callAgent(
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
// not only absolute source-root-spelled imports. Relative imports are the dominant style
// inside a nested source package — the canonical LRN-119 case (a mid-wave-extracted
// src/common/origin.py) is imported as `from ..common.origin import guard_origin`, which
// an absolute-only scan misses entirely, defeating the gate on its own motivating scenario.
// RT-001 (round-5 fresh-lens) — SOURCE-ROOT DIALECT: step 5's ABSOLUTE half is spelled
// `src.*` here, NOT `agent_sdk.*`. The whole step was ported verbatim from sdk-wave.js,
// which correctly roots absolute imports at agent_sdk — that repo's own source package.
// wave-cycle.js is, by the wrongRunnerForRepoLayout hard-abort in the Parse phase above,
// the runner for downstream agent repos ONLY, whose source root is src/ (`from src.config
// import make_settings`) and where `agent_sdk` is an INSTALLED THIRD-PARTY DEPENDENCY the
// step explicitly tells the agent to ignore. An agent_sdk-rooted resolver in that tree
// matched nothing, ever, so the absolute half of this gate was a permanent no-op in every
// repo this runner can execute in — the same dialect defect step 6 (offendingUndeclaredScope)
// had already been fixed for, one field over. test_workflows.py's
// ARCHIVE_GATE_DIALECT_CASES now pins BOTH directions per runner (required root present,
// foreign root absent) across the schema block and the prompt, so a future verbatim port
// cannot leave a stray literal behind: the build fails on the first one.
if (!protocolBlocked) {
  const archiveIntent = await callAgent(
    'Run `git status --short` and parse the output.\n\n' +
    'Scope paths for this wave (Creates: ∪ Modifies:):\n' + wave.allScope.join('\n') + '\n\n' +
    'Steps:\n' +
    '0. RT-004 (GH-131/GH-132/LRN-071/LRN-085): run `test -d template && echo yes || echo no`\n' +
    '   UNCONDITIONALLY — before anything else below, regardless of whether git status ends up\n' +
    '   clean or dirty — and set templateDirExists to true/false accordingly. This is\n' +
    '   independent of step 4b below: step 4b only inspects template/\'s DIRTY state when it is\n' +
    '   present; this step reports simply whether the directory EXISTS at all, which is the\n' +
    '   only signal this gate has for whether a wave that declares a\n' +
    '   template/.claude/workflows/<file>.js deliverable in Creates:/Modifies: can have its\n' +
    '   propagation verified in this checkout.\n' +
    '1. Run: git status --short\n' +
    '2. Collect ALL paths that appear in the output (dirty or untracked).\n' +
    '3. Cross-reference dirty paths against the scope list above for offendingPaths.\n' +
    '   A dirty path is an offender when:\n' +
    '   a. It exactly matches a scope entry, OR\n' +
    '   b. It starts with a scope entry (the scope entry is a directory prefix), OR\n' +
    '   c. A scope entry starts with the dirty path (dirty parent directory).\n' +
    '4. Separately, collect any dirty/untracked paths whose relative path starts with\n' +
    '   tests/, docs/, workspace/learning/, workspace/scenarios/results/, workspace/prd/,\n' +
    '   .claude/workflows/, harness/workflows/, .claude/agents/, harness/agents/,\n' +
    '   .claude/skills/, or harness/skills/, OR that exactly equal pyproject.toml (RT-007:\n' +
    '   a pytest-gate/dependency edit there was previously invisible to every gate clause)\n' +
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
    '   `from ..pkg.mod import Z`) in addition to ABSOLUTE `src.*` imports (`src` is THIS\n' +
    '   runner\'s source root — a downstream agent repo imports its own code as\n' +
    '   `from src.config import make_settings`; `agent_sdk` is an installed third-party\n' +
    '   dependency here, never an intra-package target, so IGNORE agent_sdk imports).\n' +
    '   Relative imports are the dominant style inside a nested source package such as\n' +
    '   src/tools/ (e.g.\n' +
    '   `from ..common.origin import guard_origin`) — a scan that resolves only absolute\n' +
    '   imports misses the canonical case this gate exists to catch, and quietly passes:\n' +
    '   a. Identify every dirty or untracked .py file from the git status output.\n' +
    '   b. For each .py file that is dirty/untracked OR listed in the scope above, read every\n' +
    '      import statement in it — both ABSOLUTE (`import src...`,\n' +
    '      `from src... import ...`) and RELATIVE (`from . import ...`,\n' +
    '      `from .mod import ...`, `from ..pkg.mod import ...`) — and resolve any intra-\n' +
    '      package target, whether spelled absolutely OR relatively, to the local .py file it\n' +
    '      names. Four forms, resolved differently:\n' +
    '        - ABSOLUTE, direct module: `import src.<dotted-path>` (one or more dotted\n' +
    '          segments — a SINGLE segment counts too, e.g. `import src.foo`) → resolve\n' +
    '          directly to `src/<dotted-path-with-/-for-.>.py` (e.g.\n' +
    '          `src.common.origin` → `src/common/origin.py`; `src.foo` →\n' +
    '          `src/foo.py`).\n' +
    '        - ABSOLUTE, from-import: `from src[.<pkg-path>] import <name>` where\n' +
    '          <pkg-path> is ZERO or more dotted segments at ANY depth — zero segments covers\n' +
    '          the bare top-level form `from src import <name>` → do NOT assume this\n' +
    '          resolves to `src/<pkg-path>/__init__.py`. First check whether\n' +
    '          `src/<pkg-path>/<name>.py` exists on disk (`<name>` is itself a submodule\n' +
    '          file at that depth; when <pkg-path> is empty, check `src/<name>.py`\n' +
    '          directly), e.g. `from src.common import origin` → check for\n' +
    '          `src/common/origin.py`. If the submodule file exists, resolve to it — this\n' +
    '          is the case a mid-wave extraction produces, and the one this gate exists to\n' +
    '          catch, no matter how many package levels deep the extraction landed. RT-001\n' +
    '          (round-5): otherwise <name> may be a SUB-PACKAGE (a directory with its own\n' +
    '          `__init__.py`) rather than a submodule file — check whether\n' +
    '          `src/<pkg-path>/<name>/__init__.py` exists on disk (when <pkg-path> is\n' +
    '          empty, check `src/<name>/__init__.py` directly); if it exists, <name> is\n' +
    '          a sub-package and resolves to THAT file, e.g. `from src import tools` →\n' +
    '          `src/tools.py` does NOT exist, but `src/tools/__init__.py` DOES\n' +
    '          (src/tools/ is a package) → resolves to `src/tools/__init__.py`.\n' +
    '          RT-004: otherwise, when <pkg-path> is NON-EMPTY, check whether\n' +
    '          `src/<pkg-path>.py` exists on disk — <pkg-path> itself names a MODULE and\n' +
    '          <name> is a symbol inside it (the from-clause names the module fully), e.g.\n' +
    '          `from src.common.origin import guard_origin` → <pkg-path> is\n' +
    '          `common.origin`; neither `src/common/origin/guard_origin.py` nor\n' +
    '          `src/common/origin/guard_origin/__init__.py` exists, but\n' +
    '          `src/common/origin.py` DOES → resolves to `src/common/origin.py`,\n' +
    '          NEVER to the nonexistent `src/common/origin/__init__.py`. Only resolve to\n' +
    '          `src/<pkg-path>/__init__.py` as the ENCLOSING package (i.e. `<name>` is a\n' +
    '          symbol re-exported from it, not a submodule, sub-package, or module) when NONE\n' +
    '          of `src/<pkg-path>/<name>.py`, `src/<pkg-path>/<name>/__init__.py`,\n' +
    '          nor (when <pkg-path> is non-empty) `src/<pkg-path>.py` exists.\n' +
    '        - RELATIVE, from-import with a module path: `from <dots><module-path> import\n' +
    '          <name>` where <dots> is one or more leading dots and <module-path> is a\n' +
    '          NON-EMPTY dotted path immediately following the dots (e.g.\n' +
    '          `from ..common.origin import guard_origin`, `from ..sources import pricing`,\n' +
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
    '          `from ..common.origin import guard_origin` inside `src/tools/quote.py` —\n' +
    '          that file lives in `src/tools`, one dot keeps that directory, the second\n' +
    '          dot walks up to `src`; appending `common/origin` gives <pkg-path>\n' +
    '          `src/common/origin`; neither `src/common/origin/guard_origin.py`\n' +
    '          nor `src/common/origin/guard_origin/__init__.py` exists, but\n' +
    '          `src/common/origin.py` DOES → resolves to `src/common/origin.py`.\n' +
    '          Worked example (submodule, RT-001):\n' +
    '          `from ..sources import pricing` inside `src/tools/quote.py` —\n' +
    '          <pkg-path> is `src/sources`; `src/sources/pricing.py`\n' +
    '          DOES exist, so `pricing` is a submodule and this resolves to that tracked\n' +
    '          file — NEVER to the nonexistent `src/sources.py`, which would be a\n' +
    '          false-positive undeclared-import block on every wave that scopes a tool file.\n' +
    '          Worked example (sub-package, RT-004): `from ..common import newsubpkg` inside\n' +
    '          `src/tools/quote.py` — <pkg-path> is `src/common`;\n' +
    '          `src/common/newsubpkg.py` does NOT exist, but\n' +
    '          `src/common/newsubpkg/__init__.py` DOES → resolves to that file, not to\n' +
    '          the nonexistent `src/common.py` a two-step ladder would have stopped at.\n' +
    '        - RELATIVE, bare: `from <dots> import <name>` where <dots> is one or more\n' +
    '          leading dots with NO module path after them (e.g. `from . import origin`\n' +
    '          inside `src/common/foo.py`) → resolve the dots to a base directory\n' +
    '          exactly as in the relative from-import form above, then check whether\n' +
    '          `<base-dir>/<name>.py` exists on disk. If it exists, resolve to that file —\n' +
    '          <name> is itself a submodule directly under that directory. RT-001 (round-5):\n' +
    '          otherwise <name> may be a SUB-PACKAGE (a directory with its own `__init__.py`)\n' +
    '          rather than a submodule file — check whether `<base-dir>/<name>/__init__.py`\n' +
    '          exists on disk; if it exists, resolve to THAT file, e.g. `from . import tools`\n' +
    '          inside `src/__init__.py` → `<base-dir>/tools.py` does NOT exist, but\n' +
    '          `<base-dir>/tools/__init__.py` DOES → resolves to it. Only resolve to\n' +
    '          `<base-dir>/__init__.py` as the ENCLOSING package (i.e. `<name>` is a symbol\n' +
    '          re-exported from it) when NEITHER `<base-dir>/<name>.py` NOR\n' +
    '          `<base-dir>/<name>/__init__.py` exists.\n' +
    '      Ignore stdlib and third-party imports. Resolve any intra-package target — whether\n' +
    '      spelled ABSOLUTELY (rooted at `src`) OR RELATIVELY (`from .`, `from ..`,\n' +
    '      etc.) — do not skip relative forms just because they do not start with\n' +
    '      `src`.\n' +
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
    '6. RT-003 (w036) undeclared-scope check, in this runner\'s own src/ dialect (the\n' +
    '   sdk-wave.js original watches agent_sdk/**.py — its repo\'s source root — and was\n' +
    '   re-dialected on the way in, exactly as step 5 above was): src/**.py files that\n' +
    '   are TRACKED\n' +
    '   (already existed before this wave) evade every check above if modified but never\n' +
    '   declared — offendingPaths only fires when the path is in the scope list,\n' +
    '   offendingHarnessPaths only watches specific harness dirs (src/ is not one),\n' +
    '   and offendingUndeclaredImports only inspects UNTRACKED .py files (`git ls-files`\n' +
    '   empty). For every dirty path from step 2 that (a) matches src/**/*.py\n' +
    '   (anywhere under src/, .py extension), (b) IS tracked — `git ls-files <path>`\n' +
    '   returns it (equivalently: its git-status-short two-letter prefix is not `??`), AND\n' +
    '   (c) is absent from the scope list above, where "present" means an EXACT string\n' +
    '   match against a scope entry and NOTHING else — add it to offendingUndeclaredScope.\n' +
    '   RT-001 (round-7 fresh-lens debug): do NOT reuse step 3\'s three offender rules\n' +
    '   here. Step 3 asks "is this dirty path declared?" to FLAG it, so matching broadly\n' +
    '   there is fail-closed; this step asks the same question to EXCUSE it, so the same\n' +
    '   breadth is fail-OPEN. Under the old wording a single directory-shaped scope entry\n' +
    '   (`agent_sdk/`, harvested from explanatory prose on a Creates: line) was a\n' +
    '   directory prefix of every dirty file beneath it, so every one of them counted as\n' +
    '   declared and this check could never fire. A scope entry declares exactly the one\n' +
    '   file it names; it never covers a subtree, a sibling, or a parent.\n' +
    '7. Return all seven fields.\n\n' +
    'If the working tree is completely clean, gitStatusOutput is empty string,\n' +
    'dirtyPaths is [], offendingPaths is [], offendingHarnessPaths is [],\n' +
    'offendingUndeclaredImports is [], offendingUndeclaredScope is []. templateDirExists is\n' +
    'NEVER defaulted by tree cleanliness — it always reflects step 0\'s independent\n' +
    '`test -d template` check.',
    { schema: ARCHIVE_INTENT_SCHEMA, label: 'gate:archive-commit', phase: 'Archive' }
  )

  // WC-001: null archiveIntent must block archive — unknown commit state is not the same as clean.
  // All other null-agent responses in this file use the same fail-closed invariant (RT-001).
  if (!archiveIntent) {
    protocolBlocked = true
    log('WARNING: archive-commit gate agent returned null — archive BLOCKED (unknown commit state). Re-run /wave ' + wave.waveId)
  } else if ((archiveIntent.offendingPaths && archiveIntent.offendingPaths.length > 0) ||
             (archiveIntent.offendingHarnessPaths && archiveIntent.offendingHarnessPaths.length > 0) ||
             (archiveIntent.offendingUndeclaredImports && archiveIntent.offendingUndeclaredImports.length > 0) ||
             (archiveIntent.offendingUndeclaredScope && archiveIntent.offendingUndeclaredScope.length > 0)) {  // RT-003 (w036)
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
    if (archiveIntent.offendingUndeclaredScope && archiveIntent.offendingUndeclaredScope.length > 0) {
      // RT-003 (w036; RT-003 fix round: agent_sdk/**.py corrected to src/**.py): a tracked
      // src/**.py file modified mid-wave but named only in a todo's Reuses:/SI: prose,
      // never added to Creates:/Modifies: — invisible to offendingPaths (undeclared),
      // offendingHarnessPaths (src/ is not a harness dir), and offendingUndeclaredImports
      // (untracked-.py-only). Staging without declaring it here loses the paper trail
      // wave.allScope exists to guarantee.
      log('Archive BLOCKED — ' + archiveIntent.offendingUndeclaredScope.length + ' tracked source file(s) are modified but undeclared:')
      archiveIntent.offendingUndeclaredScope.forEach(function(p) { log('  [undeclared scope] ' + p) })
      log('Add the file(s) above to Creates:/Modifies: in the wave/todo, then re-run /wave ' + wave.waveId)
    }
    log('Commit or stage the files above, then re-run /wave ' + wave.waveId)
  } else {
    log('Commit check passed — all scope files and harness deliverables are committed')
  }

  // RT-004 (GH-131/GH-132/LRN-071/LRN-085): hard-block archive when this wave declares a
  // template/ deliverable but template/ is not checked out in this working tree — independent
  // of the commit-check branches above, since a missing checkout means propagation cannot be
  // verified at all, not merely that it is uncommitted. Steps 4/4b/6 above only ever detect a
  // DIRTY template/ mirror; this is the only check in this gate that fires when template/ is
  // absent entirely — an xfail(strict=True) test-report signal is not a substitute for it.
  const declaresTemplateScope = wave.allScope.some(function(p) { return p.startsWith('template/') })
  if (declaresTemplateScope && archiveIntent && archiveIntent.templateDirExists === false) {
    protocolBlocked = true
    templatePropagationBlocked = true
    log('ARCHIVE BLOCKED — wave ' + wave.waveId + ' declares a template/ deliverable but template/ is not checked out in this working tree:')
    wave.allScope.filter(function(p) { return p.startsWith('template/') })
      .forEach(function(p) { log('  [template/ absent] ' + p) })
    log('Clone the peer repo (wailuen/a2a-agent-template, LRN-071) into template/ at the repo root, ' +
        'copy the declared file(s) in from their harness/workflows/ source, verify `diff` is empty, ' +
        'then `git -C template/ commit && git -C template/ push`. Re-run /wave ' + wave.waveId +
        ' once template/ is checked out and the propagation is verified.')
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
  } else if (templatePropagationBlocked) {
    // RT-004: distinct from the generic protocol-findings message below — this wave is
    // blocked because template/ propagation is unverifiable, not a protocol audit finding.
    // /agent-verify would not fix this; checking out template/ would.
    log('Archive SKIPPED — wave ' + wave.waveId + ' declares a template/ deliverable but template/ is not checked out (see ARCHIVE BLOCKED detail above).')
    log('Clone wailuen/a2a-agent-template into template/, land the propagated file(s), then re-run /wave ' + wave.waveId + '.')
  } else if (phaseBudgetBlocked) {
    // RT-003 (this wave): distinct from the generic protocol-findings message below — this
    // wave is blocked because the phase redteam round budget was exhausted with surviving
    // critical/high findings, not a protocol audit finding. /agent-verify would not fix this;
    // fixing the findings in the deferred note would.
    log('Archive SKIPPED — wave ' + wave.waveId + ' blocked: phase redteam round budget exhausted with surviving critical/high findings.')
    log('Fix the findings in workspace/todos/deferred/' + wave.waveId + '-phase-budget-exhausted.md, then re-run /wave ' + wave.waveId + '.')
  } else if (unitBudgetBlocked) {
    // RT-004 (this wave): mirrors phaseBudgetBlocked above, for a per-group unit redteam round
    // budget exhausted with surviving critical/high findings.
    log('Archive SKIPPED — wave ' + wave.waveId + ' blocked: unit redteam round budget exhausted with surviving critical/high findings for at least one group.')
    log('Fix the findings in the affected group\'s workspace/todos/deferred/' + wave.waveId + '-group-<label>-budget-exhausted.md, then re-run /wave ' + wave.waveId + '.')
  } else if (redteamUnknownBlocked) {
    // RT-003 (this wave, LRN-032): distinct from both the generic protocol-findings message
    // below AND from phaseBudgetBlocked/unitBudgetBlocked above — this wave is blocked because
    // a redteam round budget was exhausted while the verdict itself was never established
    // (persistent null response, or a findingsCount/findings mismatch), not because critical/
    // high findings actually survived review. /agent-verify would not fix this; obtaining a
    // trustworthy redteam verdict would.
    log('Archive SKIPPED — wave ' + wave.waveId + ' blocked: redteam never returned a trustworthy verdict (persistent null response or findingsCount mismatch) within its round budget.')
    log('See the workspace/todos/deferred/' + wave.waveId + '-*-rt-null-budget.md / -rt-mismatch-budget.md note(s), then re-run /wave ' + wave.waveId + '.')
  } else {
    log('Archive SKIPPED — wave ' + wave.waveId + ' blocked by critical protocol findings')
    log('Fix protocol issues, run /agent-verify, then re-run /wave ' + wave.waveId)
  }
} else {
  await callAgent(
    'Archive wave ' + wave.waveId + '. Perform in order:\n\n' +
    '1. RT-004 (never overwrite): check whether `workspace/todos/completed/' + WAVE_BASENAME +
    '` already exists. It must NOT — the Parse-phase gate already hard-blocked this run if it did — ' +
    'but if you find it exists anyway (e.g. created by a concurrent process since Parse ran), ' +
    'STOP: do NOT move or overwrite it. Leave `' + WAVE_FILE + '` in place, report the collision, ' +
    'and skip the rest of this step. Otherwise, move `' + WAVE_FILE + '` → `workspace/todos/completed/` (same filename).\n\n' +
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
    '   ALL findings in it are marked RESOLVED (no OPEN findings remain). If so, first check\n' +
    '   whether `workspace/todos/completed/<that file\'s own basename>` already exists — if it\n' +
    '   does, do NOT overwrite it; skip that one file, report the collision, and continue with\n' +
    '   the rest of the sweep. Otherwise `mv` it to `workspace/todos/completed/` (same filename)\n' +
    '   — `deferred/` must only ever contain files with at least one OPEN finding. Leave files\n' +
    '   with any OPEN finding in place.\n\n' +
    'Report: file moved (or the collision reported instead), plan.md updated (row updated or\n' +
    'appended), FR fields updated, and the list of any deferred markers relocated by the step-4\n' +
    'sweep (or none, or any step-4 collisions skipped).',
    { label: 'archive', phase: 'Archive' }
  )

  // LRN-062 / RT-001: the archive agent's plan.md instructions above are not self-enforcing —
  // verify the row actually landed instead of trusting the report. On miss, self-heal with one
  // targeted append attempt; if that also fails, hard-block the wave as incomplete rather than
  // let it silently vanish from the ledger (the exact recurrence this guard exists to catch).
  // RT-008: waveFileTag is this wave's own File-column value (same transform used to build the
  // row above) — reused below so the presence check requires BOTH wave.waveId AND this wave's
  // own file, not waveId alone. See the PLAN_ROW_SCHEMA comment for why: waveId alone lets a
  // different wave that reused the same id satisfy this wave's check via ITS row.
  const waveFileTag = WAVE_FILE.replace('workspace/todos/', '')
  const planRowCheck = await callAgent(
    'Run: grep -i "' + wave.waveId + '" workspace/todos/plan.md | grep -ci -F "' + waveFileTag + '"\n' +
    'Report rowPresent: true if the count is >= 1, else false. Report the count as matchCount.',
    { schema: PLAN_ROW_SCHEMA, label: 'gate:archive-plan-row', phase: 'Archive' }
  )

  if (!planRowCheck || !planRowCheck.rowPresent) {
    log('WARNING: workspace/todos/plan.md has no row for ' + wave.waveId + ' (file ' + waveFileTag + ') after archive — self-healing (LRN-062 guard)')
    await callAgent(
      'workspace/todos/plan.md is missing a ledger row for wave ' + wave.waveId + ' (file ' + waveFileTag + ') even though it was ' +
      'just archived to workspace/todos/completed/ (or workspace/todos/archive/). Append this exact row ' +
      'to the end of the Wave summary table that this wave belongs to (the table with columns ' +
      'Wave | File | Parallel group | Slices | Depends). If a row for this waveId already exists but its ' +
      'File column names a DIFFERENT file, that row belongs to a different wave that reused this waveId ' +
      '(RT-008) — leave it untouched and append a new row for THIS wave instead of editing it:\n' +
      '`| ' + wave.waveId.toUpperCase() + ' [x] ✅ ' + TODAY + ' | ' + waveFileTag + ' | G | — | — |`\n' +
      'Do not modify or remove any other row.',
      { label: 'archive-plan-row-repair', phase: 'Archive' }
    )

    const planRowRecheck = await callAgent(
      'Run: grep -i "' + wave.waveId + '" workspace/todos/plan.md | grep -ci -F "' + waveFileTag + '"\n' +
      'Report rowPresent: true if the count is >= 1, else false. Report the count as matchCount.',
      { schema: PLAN_ROW_SCHEMA, label: 'gate:archive-plan-row-recheck', phase: 'Archive' }
    )

    if (!planRowRecheck || !planRowRecheck.rowPresent) {
      archivePlanRowMissing = true
      log('BLOCKED — workspace/todos/plan.md still has no row for ' + wave.waveId + ' (file ' + waveFileTag + ') after repair attempt.')
      log('Archive is INCOMPLETE — add the row manually, then re-run /wave ' + wave.waveId + ' to confirm.')
    } else {
      log('plan.md row for ' + wave.waveId + ' (file ' + waveFileTag + ') appended by self-heal guard')
    }
  }

  log('Wave ' + wave.waveId + ' archived — ' + lrnCandidates.length + ' LRN(s) captured')
}

return {
  waveId:               wave.waveId,
  totalTodos:           totalTodos,
  lrnsCaptured:         lrnCandidates.length,
  cNnnRegistered:       registryCandidates.length,
  sdkCandidates:        sdkCandidatesCount,
  groupsExecuted:       wave.groups.length,
  phaseRedteamRounds:   pRound,
  exhausted:            pRound >= 8,
  protocolBlocked:      protocolBlocked,
  testsRed:             testsRed,
  testsBlockedArchive:  testsBlockedArchive,  // RT-003: distinguishes test-suite block from protocol block
  archivePlanRowMissing: archivePlanRowMissing,  // LRN-062 / RT-001: plan.md ledger row missing after self-heal
  unitBudgetBlocked:    unitBudgetBlocked,   // RT-004 (this wave): a group's unit redteam round budget was exhausted with surviving critical/high findings
  phaseBudgetBlocked:   phaseBudgetBlocked,  // RT-003 (this wave): the phase redteam round budget was exhausted with surviving critical/high findings
  redteamUnknownBlocked: redteamUnknownBlocked,  // RT-003 (this wave, LRN-032): a redteam round budget was exhausted with the verdict itself never established (null response or findingsCount mismatch)
}
