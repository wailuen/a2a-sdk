export const meta = {
  name: 'sdk-wave',
  description: 'SDK-context wave executor: todos redteam → tier-parallel implement → unit zero-tolerance redteam (severity floor: only critical/high findings block; debug fires unconditionally at round 4+ (uRound > 3) and at any round when stall is detected, replacing the fix fan-out that round; round 5 exits via deferred note) → phase zero-tolerance redteam (same severity floor; debug fires unconditionally at round 4+ (pRound > 3) and at any round when stall is detected, replacing the fix fan-out that round; round 8 exits) → protocol audit → codify → archive. All harness agentTypes are used: redteam, python-implementer, debug, codify (populated in harness/agents/core/ since 2026-06-16), plus advisor agentTypes (a2a-advisor etc.).',
  phases: [
    { title: 'Parse',          detail: 'Read wave file; extract groups, creates paths, groupDeps, LRN baseline' },
    { title: 'Todos Redteam',  detail: 'Redteam the wave plan: SI risk annotation, registry reuse (Reuses: C-NNN), new component candidate flagging' },
    { title: 'Implement',      detail: 'Tier-based parallel fan-out (groupDeps); scoped pytest per todo; no full-suite run until gate' },
    { title: 'Unit Redteam',   detail: 'Per-group zero-tolerance fix loop (max 5 rounds/group; severity floor — only critical/high findings block, medium/low deferred; debug fires unconditionally at round 4+ (uRound > 3) and at any round when stall is detected (same findings as previous round), replacing the fix fan-out that round; round 5 exits via deferred note)' },
    { title: 'Phase Redteam',  detail: 'Full-wave zero-tolerance fix loop (max 8 rounds; severity floor — only critical/high findings block, medium/low deferred; debug fires unconditionally at round 4+ (pRound > 3) and at any round when stall is detected (same findings as previous round), replacing the fix fan-out that round; round 8 exits)' },
    { title: 'Protocol Audit', detail: 'a2a-advisor / mcp-advisor / ag-ui-advisor / a2ui-advisor in parallel (only for touched protocol surfaces) + seam check' },
    { title: 'Codify',         detail: 'SDK issue scan → parallel LRN capture → README index → C-NNN registration' },
    { title: 'Archive',        detail: 'Pre-archive pytest gate + commit-intent guard (GH-40/GH-84) → move to completed/ → update plan.md' },
  ],
}

// ─── args ─────────────────────────────────────────────────────────────────────
// args.waveFile : absolute path to the active wave file
// args.today    : ISO date string for archive timestamps (e.g. "2026-06-16")
// GH-131 (ported from wave-cycle.js): the workflow sandbox bans the Date global
// outright, so a Date-based fallback for a missing args.today always throws when it
// fires — and it fires whenever args arrives JSON-encoded as a string (making
// args.today read as undefined through the object accessor), producing a Date-related
// crash with zero agents spawned instead of an error naming the actual missing arg.
// Normalize args first (string-encoded args are parsed; a missing/falsy args becomes
// {}), then fail fast naming whichever field(s) are absent — never fall back to Date.
// RT-006 (ported from wave-cycle.js RT-017): GH-131's AC is to fail fast with a clear
// error naming the missing arg(s) — a string args payload that is not valid JSON must
// not still die with a bare, unattributed SyntaxError one layer up from the exact
// failure mode GH-131 removed.
let normalizedArgs
if (typeof args === 'string') {
  try {
    normalizedArgs = JSON.parse(args)
  } catch (e) {
    throw new Error(
      'sdk-wave: args arrived as a string but is not valid JSON — pass { waveFile, today } ' +
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
    'sdk-wave: missing required arg(s): ' + missingArgs.join(', ') +
    ' — pass { waveFile, today } (or a JSON-encoded string of the same shape).'
  )
}
const WAVE_FILE = normalizedArgs.waveFile
const TODAY     = normalizedArgs.today
// RT-004 (w036/w039 wave-ID collision, ported from wave-cycle.js): a reused wave ID
// whose basename already exists under workspace/todos/completed/ makes the archive
// step's `mv` silently overwrite the earlier wave's record — no runner checked for
// this. WAVE_BASENAME anchors both the Parse-phase hard-block below and the
// archive-step anti-overwrite instruction to the same value.
const WAVE_BASENAME = WAVE_FILE.split('/').pop()

// ─── protocol surface paths — SDK repo layout ─────────────────────────────────
// LRN-132/GH-123: agent_sdk/routes/oauth is the OAuth discovery/token
// endpoints surface (PRM/authorize/token/register/revoke), not the store
// that backs require_identity. require_identity (defined in
// agent_sdk/auth/middleware.py) delegates credential verification to
// OAuthTokenStore in agent_sdk/auth/oauth_tokens.py via
// runtime.oauth.verify(). Both routes/oauth and middleware are shared
// surfaces every protected A2A, AG-UI, and MCP route depends on — not
// MCP-only. RT-001: middleware.py itself must also be a shared surface
// member — it is the file that actually DEFINES require_identity and is
// consumed directly via Depends() by all four route files. AUTH_SURFACE
// holds both paths and is folded into all three protocol arrays so a wave
// touching only oauth.py OR only middleware.py still dispatches
// a2a-advisor and ag-ui-advisor, not mcp-advisor alone.
// RT-001 (round 2): middleware.py only calls into the credential-verification
// implementations — agent_sdk/auth/oauth_tokens.py (OAuthTokenStore.verify)
// and agent_sdk/auth/api_keys.py (ApiKeyStore.verify) are what actually gate
// every protected route. Neither was a surface member, so a wave touching
// only oauth_tokens.py (e.g. an audience-binding regression) dispatched no
// protocol advisor at all. Both are added to AUTH_SURFACE for the same
// reason middleware.py was: trace the transitive runtime consumers of
// require_identity, not just its direct Depends() target.
// RT-003 (round 5): both verify() backends (oauth_tokens.py:377, api_keys.py:94)
// `from .identity import Identity` and return an Identity — the object
// require_identity yields to every protected route's Depends(). By the same
// "trace transitive require_identity consumers" rule that added oauth_tokens
// and api_keys, agent_sdk/auth/identity.py belongs in AUTH_SURFACE too — a wave
// touching only identity.py (e.g. a binding-key or kind-tag regression on the
// dataclass every audience check relies on) previously dispatched no protocol
// advisor at all.
const AUTH_SURFACE = [
  'agent_sdk/routes/oauth',
  'agent_sdk/auth/middleware',
  'agent_sdk/auth/oauth_tokens',
  'agent_sdk/auth/api_keys',
  'agent_sdk/auth/identity',
]
const A2A_SURFACE  = ['agent_sdk/routes/a2a', 'agent_sdk/routes/agent_card', 'agent_sdk/models/a2a'].concat(AUTH_SURFACE)
const MCP_SURFACE  = ['agent_sdk/routes/mcp'].concat(AUTH_SURFACE)
const AGUI_SURFACE = ['agent_sdk/routes/ag_ui'].concat(AUTH_SURFACE)
// RT-003 (fix wave): A2UI_SURFACE deliberately does NOT fold in AUTH_SURFACE, unlike
// A2A_SURFACE/MCP_SURFACE/AGUI_SURFACE above. A2UI has no transport of its own — it is
// delivered exclusively as an A2A DataPart or an AG-UI CUSTOM event, so a wave touching
// only an AUTH_SURFACE file already sets runA2A/runAGUI (both fold in AUTH_SURFACE),
// dispatching a2a-advisor/ag-ui-advisor plus the unconditional seam leg below — the
// layer where A2UI's transport-level auth is actually enforced and audited. Folding
// AUTH_SURFACE in here too would dispatch a2ui-advisor on every auth-only wave for no
// added coverage: a2ui-advisor audits component/message-shape conformance, not
// authentication. Unlike AUTH_SURFACE's fold into the three transport arrays (a genuine
// under-triggering risk closed by GH-123/LRN-132), omitting it here is not an
// under-trigger — it is a documented exception, not a silent gap. Mirrors
// wave-cycle.js's identical rationale above its own A2UI_SURFACE.
const A2UI_SURFACE = ['agent_sdk/a2ui/', 'agent_sdk/models/content_types']

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
    completedFileExists: { type: 'boolean', description: 'RT-004: true if workspace/todos/completed/<basename of the wave file> already exists (`test -f workspace/todos/completed/<basename> && echo yes || echo no`), determined UNCONDITIONALLY while parsing — a reused wave ID whose basename collides with an already-archived wave would have its record silently overwritten by the archive step\'s mv-by-basename' },
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
    // RT-014 / LRN-085 (RT-004/LRN-131: ported from wave-cycle.js — this runner, not
    // wave-cycle.js, is the one that actually executes in the a2a-sdk repo where the
    // harness/workflows/*.js -> template/.claude/workflows/*.js propagation gap can
    // occur; downstream agent repos wave-cycle.js runs in ship neither directory):
    // a todo whose Creates:/Modifies: touches harness/workflows/*.js or
    // .claude/workflows/*.js but omits the template/.claude/workflows/<file>.js
    // peer-repo mirror (wailuen/a2a-agent-template) leaves propagation to
    // out-of-band action. See LRN-071 (template/ is a peer repo, not a submodule).
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
// (tests/, docs/, workspace/learning/, workspace/scenarios/results/, workspace/prd/, .claude/workflows/,
// harness/workflows/, .claude/agents/, harness/agents/, .claude/skills/, harness/skills/) plus the
// single-file entry pyproject.toml (RT-007, below) as
// offendingHarnessPaths. Post-archive w035 follow-up: the workflow-file
// dirs were added after a GH-118 fix (RT-003) landed in wave-cycle.js without either
// wave.allScope or this dir list watching wave-cycle.js/sdk-wave.js's own directories — an
// undeclared workflow-file edit could evade offendingPaths AND offendingHarnessPaths at once.
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
// harness dir (evading offendingHarnessPaths), not under agent_sdk/**.py (evading
// offendingUndeclaredScope), not a .py import target (evading offendingUndeclaredImports), and
// simply never named in a todo's Creates:/Modifies: (evading offendingPaths) — a sixth variant
// of the double-blind-spot class documented above. A pytest.ini_options edit (e.g. a
// filterwarnings entry broad enough to mask a genuine leaked event loop or socket) could land
// fully undetected by this gate. Fix: pyproject.toml was added to the dir list above as a
// single-file entry (and the matching schema description / prompt step 4 text below) — `starts
// with` matching degenerates to an exact match for a top-level file with no children.
// GH-118 (LRN-119): the checks above only catch paths git already sees as dirty/untracked
// AND either in wave.allScope or under a harness dir — they never inspect import statements.
// A module extracted mid-wave (e.g. agent_sdk/common/origin.py in GH-110) that sits
// untracked, is imported by a declared file, but is itself outside both allScope and the
// harness dirs produces no offending entry and silently passes the gate — risking an
// ImportError at boot on every importing surface if archive stages only declared paths.
// offendingUndeclaredImports closes that gap: it holds resolved agent_sdk.* import targets
// of dirty/scope .py files that are themselves untracked and undeclared.
// RT-003 (w036, post-archive gh-issues review): a THIRD blind spot, orthogonal to the two
// above — a file that is TRACKED (already existed pre-wave, so offendingUndeclaredImports'
// `git ls-files` check never flags it), modified mid-wave, named only inside a todo's
// Reuses:/SI: prose annotation (never its own Creates:/Modifies: line, so it evades
// offendingPaths), and outside every harness deliverable dir (so it evades
// offendingHarnessPaths too). GH-135/GH-130 each hit this exact gap on tracked
// agent_sdk/**.py files (agent_sdk/routes/mcp.py, agent_sdk/routes/admin.py,
// agent_sdk/__init__.py, agent_sdk/common/redact.py). offendingUndeclaredScope closes it:
// any dirty, TRACKED agent_sdk/**.py path absent from wave.allScope is flagged as
// undeclared scope drift and blocks archive, same as the other three checks.
// RT-002 (LRN-131): RT-004 (GH-131/GH-132/LRN-071/LRN-085) — steps 4/4b and step 6 above only
// ever detect a DIRTY template/.claude/workflows/ mirror — they say nothing when template/ is
// not checked out in this working tree at all. GH-131 and GH-132 both declared
// template/.claude/workflows/wave-cycle.js as a deliverable in Modifies:, yet template/ is a
// gitignored peer repo (LRN-071) that can be entirely absent from a checkout — in that case
// step 4b's own guard ("If a `template/` directory exists...") never fires, so this gate
// silently reports a clean archive-commit check even though the declared propagation was never
// verified. This RT-004 hard-block originally landed only in the three wave-cycle.js copies —
// sdk-wave.js is the runner .claude/skills/wave/SKILL.md step 2 actually launches, so it was
// left exposed to the identical failure class. templateDirExists below, plus the
// declaresTemplateScope hard-block after the archiveIntent response further down, close that
// gap here too: a wave that declares a template/ path as scope hard-blocks archive, loudly,
// whenever template/ is not checked out.
// RT-012 (post-archive gh-issues review): docs/content-types.md landed 64 net-new lines
// documenting the GH-130/RT-011 delimiter-safety contract with no todo declaring it in
// Creates:/Modifies: — invisible to offendingPaths (undeclared), offendingHarnessPaths (docs/
// was not a watched dir), offendingUndeclaredImports (not a .py file), AND
// offendingUndeclaredScope (not under agent_sdk/**.py) simultaneously: a fifth variant of the
// same double-blind-spot RT-003/RT-007 closed for other file classes above. Fix: docs/ was
// added to the harness-deliverable dir list (HARNESS_DIRS in tests/test_workflows.py, and the
// matching schema description / prompt step 4 text below, in all three archive-gate runners).
// RT-006 (round-7 fresh-lens debug): the Parse-phase template-dir fast-abort landed only in
// the two wave-cycle.js mirrors. sdk-wave.js carried the LATE archive-gate hard-block below
// but no Parse gate at all — so a wave declaring a template/ deliverable in this repo (whose
// own open deliverable IS a template/ propagation) burned its entire agent-call budget on
// Implement/Redteam/Codify before discovering at archive time that the propagation could never
// land. That is the precise waste the wave-cycle.js gate was written to prevent. A minimal,
// single-purpose schema (deliberately NOT reusing ARCHIVE_INTENT_SCHEMA's full commit-check
// shape, which needs git status output this early check has no use for) lets the Parse-phase
// gate ask the same `test -d template` question cheaply, before any expensive phase starts.
const TEMPLATE_DIR_CHECK_SCHEMA = {
  type: 'object',
  required: ['templateDirExists'],
  additionalProperties: false,
  properties: {
    templateDirExists: { type: 'boolean', description: 'True if a `template/` directory exists at the repo root (`test -d template`)' },
  },
}

const ARCHIVE_INTENT_SCHEMA = {
  type: 'object',
  required: ['gitStatusOutput', 'dirtyPaths', 'offendingPaths', 'offendingHarnessPaths', 'offendingUndeclaredImports', 'offendingUndeclaredScope', 'templateDirExists'],
  additionalProperties: false,
  properties: {
    gitStatusOutput:      { type: 'string', description: 'Raw stdout of git status --short' },
    dirtyPaths:           { type: 'array', items: { type: 'string' }, description: 'All paths reported dirty or untracked by git' },
    offendingPaths:       { type: 'array', items: { type: 'string' }, description: 'Dirty paths that overlap with wave.allScope (Creates: ∪ Modifies:)' },
    offendingHarnessPaths: { type: 'array', items: { type: 'string' }, description: 'Dirty/untracked paths under tests/, docs/, workspace/learning/, workspace/scenarios/results/, workspace/prd/, .claude/workflows/, harness/workflows/, .claude/agents/, harness/agents/, .claude/skills/, or harness/skills/, or exactly matching the single-file entry pyproject.toml (step 4) — plus, per step 4b, any dirty .claude/workflows/ path from `git -C template status --short` (the nested template repo), resolved to template/.claude/workflows/<file> — even if not in allScope' },
    offendingUndeclaredImports: { type: 'array', items: { type: 'string' }, description: 'GH-118/LRN-119/RT-001: resolved import targets (absolute agent_sdk.* OR relative from ./from ..) of dirty/scope .py files that are untracked (git ls-files empty) AND absent from wave.allScope' },
    offendingUndeclaredScope: { type: 'array', items: { type: 'string' }, description: 'RT-003 (w036): dirty paths under agent_sdk/**.py that ARE TRACKED (git ls-files returns them, unlike offendingUndeclaredImports which only inspects untracked .py files) but absent from wave.allScope — a source file modified mid-wave and named only in a todo\'s Reuses:/SI: prose, never added to Creates:/Modifies:. agent_sdk/ is not a harness dir, so offendingHarnessPaths cannot see it either' },
    templateDirExists:    { type: 'boolean', description: 'RT-004: true if a `template/` directory exists at the repo root (`test -d template`), determined UNCONDITIONALLY in step 0 below regardless of git status or tree cleanliness — the only signal this gate has for whether a wave that declares a template/ path in scope can have its propagation verified in this checkout' },
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

// GH-132 (ported from wave-cycle.js): severity floor — only critical/high findings
// block the unit/phase redteam loops. Gating loop exit on raw findingsCount (every
// severity, including low) meant an adversarial reviewer's routine low-severity nit
// was enough to force the round cap every time. Medium/low findings are still
// surfaced (recorded once to a deferred note on every loop exit — RT-009, see
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

// RT-009 (ported from wave-cycle.js — RT-002: this fix originally landed only in the
// wave-cycle.js mirrors, leaving this runner, the one .claude/skills/wave/SKILL.md
// launches for SDK waves, silently dropping every medium/low finding on all but the
// clean-exit path): the clean-exit branch (blocking.length === 0) was the ONLY
// loop-exit path that wrote the medium/low deferred note — the null-gate break,
// findings-mismatch break, and tests-red break all exited the same while(true) loop
// with that round's non-blocking findings computed and then discarded. Every round now
// accumulates its nonBlockingFindings into a loop-scoped store (deduped by the same
// file+description key sigs() uses, so a finding resurfacing across rounds is recorded
// once, not once per round); the caller writes ONE deferred note from ONE place after
// the loop, regardless of which break fired.
function accumulateNonBlocking(store, seenSigs, findings) {
  for (const f of nonBlockingFindings(findings)) {
    const sig = f.file + ':' + f.description
    if (!seenSigs.has(sig)) {
      seenSigs.add(sig)
      store.push(f)
    }
  }
}

// GH-132: batch the fix fan-out into ONE agent per round covering every file, unless
// the round's blocking findings span more files than this threshold — a single prompt
// spanning too many files risks losing per-file fidelity, so past the threshold the
// loop falls back to the original one-agent-per-file parallel fan-out.
const FIX_BATCH_FILE_THRESHOLD = 6

// GH-132: hard cap on LRN files captured per wave. Findings beyond the cap were
// already fixed by the redteam loop above — only individual LRN codification is
// capped, so an unusually finding-heavy wave cannot fan out one parallel codify agent
// per finding with no ceiling.
const MAX_LRN_PER_WAVE = 20

// ─── agent-call budget (hard backstop) ────────────────────────────────────────
// GH-132: with the severity floor and debug-replaces-fix-fan-out changes above,
// steady-state agent-call volume per wave should collapse on its own — but as a
// backstop against any future or unforeseen runaway loop (e.g. a stalled loop, or an
// unusually wide finding set), every dispatched agent call is counted against a hard
// per-wave ceiling. Exceeding it stops the wave LOUDLY (throws) instead of silently
// continuing to spend agent calls.
// RT-002: overridable via args.agentBudget (the same Workflow(...) args object that carries
// waveFile/today) so a wave whose honest cost exceeds the default does not throw at the same
// point on every retry with no escape hatch short of editing this file. Number(...) so a
// JSON-encoded numeric string resolves correctly (normalizedArgs above already handles the
// string-encoded-args case).
// RT-006 (ported from wave-cycle.js): a flat 150-call ceiling is documented as already below
// the honest cost of a routine 4-group wave (~4x20 unit-loop + ~32 phase + 24 codify +
// implement + archive) — a hard backstop set below normal usage aborts waves that would
// otherwise complete, with no signal short of an operator already knowing to pass
// args.agentBudget. Recomputed below (see "AGENT_CALL_BUDGET recompute") once
// wave.groups.length is known, so the ceiling scales with the wave's own shape instead of a
// fixed constant; 150 here is only the floor used for the handful of calls before Parse
// resolves the wave. An explicit args.agentBudget of exactly 0 is invalid (silently falling
// back to a default via `0 || default` would hide a typo'd override), so it is rejected below
// rather than tolerated. RT-011 (fix round, ported from wave-cycle.js): an exact-zero override
// is not the only invalid shape — Number('abc') is NaN, not 0, so a typo'd override would sail
// past a zero-only check, and the very next line's `Number(x) || default` pattern would then
// silently swallow the NaN into the default too (NaN is falsy, same as 0) — the exact gap
// wave-cycle.js's RT-015 fix closed there but this file never carried. Validate the full
// contract ONCE, here: any provided override must be a finite, positive number — this single
// guard covers exactly-zero (0 fails `> 0`), negative, non-finite, and non-numeric overrides
// alike, in one throw site rather than a dedicated zero-only guard plus a separate general one.
if (normalizedArgs.agentBudget !== undefined && normalizedArgs.agentBudget !== null &&
    !(Number.isFinite(Number(normalizedArgs.agentBudget)) && Number(normalizedArgs.agentBudget) > 0)) {
  throw new Error(
    'sdk-wave: agentBudget must be a positive number if provided (got ' +
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
      'Workflow(...) call that launches sdk-wave.js), e.g. args: { waveFile, today, ' +
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
let registryCandidates  = []
let sdkCandidatesCount  = 0

// ─── phase 0: parse wave file ─────────────────────────────────────────────────
phase('Parse')

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

if (!wave.waveId) {
  log('ERROR: wave file parsed but waveId is undefined — aborting (harness bug, not a clean wave)')
  return { error: 'missing-wave-id' }
}
// RT-004 (w036/w039 wave-ID collision, ported from wave-cycle.js): hard-block BEFORE any
// other Parse-phase work when this wave's basename already exists in
// workspace/todos/completed/ — proceeding would let the archive step silently overwrite
// the earlier wave's record via mv-by-basename. Fail fast and name the fix instead of
// discovering the collision only at archive time.
if (wave.completedFileExists) {
  log('ERROR: wave ID collision — workspace/todos/completed/' + WAVE_BASENAME + ' already ' +
      'exists. Archiving ' + WAVE_FILE + ' under this ID would overwrite the earlier wave\'s ' +
      'record. Rename this wave file (and any workspace/todos/deferred/' + wave.waveId +
      '-*.md markers) to an unused wave ID, then re-run.')
  return { error: 'wave-id-collision', waveId: wave.waveId, completedFile: 'workspace/todos/completed/' + WAVE_BASENAME }
}
// RT-012: now that wave.waveId is known, the budget-exceeded deferred note (if the ceiling
// is ever hit later in this run) can name it precisely instead of falling back to WAVE_FILE.
waveIdForBudgetNote = wave.waveId

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

// RT-006 (ported from wave-cycle.js): now that wave.groups.length is known, widen the hard
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

// RT-006 (round-7 fresh-lens debug), ported verbatim from .claude/workflows/wave-cycle.js:
// a wave that declares a template/ peer-repo deliverable in Creates:/Modifies: but runs from
// a checkout where template/ (wailuen/a2a-agent-template, LRN-071) was never cloned cannot
// have that deliverable land — no amount of Implement/Redteam/Codify work changes that.
// Discovering it only at the archive gate below means every one of those phases already ran
// and spent the wave's agent-call budget on work whose declared propagation was never
// landable. Fail fast here instead, before any of them start.
const parseDeclaresTemplateScope = wave.allScope.some(function(p) { return p.startsWith('template/') })
if (parseDeclaresTemplateScope) {
  const templateCheck = await callAgent(
    'Run `test -d template && echo yes || echo no` at the repo root and report the result.',
    { schema: TEMPLATE_DIR_CHECK_SCHEMA, label: 'gate:template-dir-check', phase: 'Parse' }
  )
  // Fail-closed (the RT-001/WC-001 convention used throughout this file): a null response
  // means unknown state, which is not the same as template/ being present.
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

log('Wave ' + wave.waveId + ': ' + wave.groups.length + ' group(s), ' +
    wave.allScope.length + ' scope path(s) (' + wave.allCreates.length + ' create / ' +
    wave.allModifies.length + ' modify), lrnNext=' + wave.lrnNext)

const lrnBase         = wave.lrnNext
const allHighFindings = []
let   protocolBlocked    = false
let   testsBlockedArchive = false   // RT-003: tracks when a red test suite (not protocol) blocks archive
let   templatePropagationBlocked = false  // RT-004 (LRN-131): archive blocked because this wave declares a template/ deliverable but template/ is not checked out (GH-131/GH-132/LRN-071/LRN-085)
let   redteamUnknownBlocked = false  // RT-003 (this wave, LRN-032; ported from wave-cycle.js): a redteam round budget was exhausted while the verdict was never established (persistent null response, or a findingsCount/findings mismatch) — archive must not proceed on an UNKNOWN verdict
let   unitBudgetBlocked   = false    // RT-001 (ported from wave-cycle.js): a group's unit redteam loop exited on the round-5 budget cap with surviving critical/high findings — archive must not proceed as if clean
let   phaseBudgetBlocked  = false    // RT-001 (ported from wave-cycle.js): the phase redteam loop exited on the round-8 budget cap with surviving critical/high findings — archive must not proceed as if clean
let   testsRed            = false
let   totalTodos          = 0

// ─── phase 1: todos redteam ───────────────────────────────────────────────────
phase('Todos Redteam')

const planRt = await callAgent(
  'Review the todo plan for wave ' + wave.waveId + ' BEFORE implementation starts.\n\n' +
  'Wave file: ' + WAVE_FILE + '\n' +
  'Also read:\n' +
  '  - workspace/components/README.md  (C-NNN registry)\n' +
  '  - workspace/learning/README.md    (past learnings + Prevention clauses)\n\n' +
  'Check ONLY these five things:\n' +
  '1. REGISTRY REUSE — does a C-NNN component already cover this todo\'s capability?\n' +
  '   If yes, add to reuseAnnotations.\n' +
  '2. SI RISK — does this todo touch auth, credential, or transport code?\n' +
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
        return callAgent(
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
            return callAgent(
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
  // RT-009: accumulates every round's non-blocking findings, across ALL loop-exit paths —
  // written once, after the loop, regardless of which break fired.
  let groupNonBlocking = []
  let groupNonBlockingSigs = new Set()

  while (true) {
    uRound++

    const rt = await callAgent(
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

    // RT-004 (ported from wave-cycle.js): null redteam response is unknown state —
    // must not be treated as clean (fail-open). This is the exact LRN-020/023/030
    // fail-open family: null and zero-findings must never share a branch. Do NOT
    // reset prevSigs on null — preserve the last real finding set so stall detection
    // against the most recent real finding set remains intact.
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
        // RT-003 (this wave, LRN-032; ported from wave-cycle.js): an UNKNOWN verdict
        // (persistent null response) must block archive at least as hard as one where
        // findings actually survived — writing a deferred note without setting a blocking
        // flag was fail-open, the exact LRN-019/LRN-023/LRN-028/LRN-030 class.
        protocolBlocked = true
        redteamUnknownBlocked = true
        break
      }
      continue
    }

    // Cross-validate findingsCount against findings.length — an agent returning
    // findingsCount=0 with a non-empty array would break clean despite real findings.
    if (rt.findingsCount === 0 && rt.findings.length > 0) {
      log('WARNING: findingsCount=0 but findings array has ' + rt.findings.length + ' item(s) — treating as non-clean')
      rt.findingsCount = rt.findings.length
    }

    // RT-007 / GH-132 (ported from wave-cycle.js): the inverse mismatch — findingsCount>0
    // with an EMPTY findings array — is schema-valid (RT_SCHEMA sets no minItems) but would
    // break the loop clean on `blocking.length === 0` below, since blocking is derived from
    // rt.findings, not findingsCount. Treat exactly like a null response — unknown state,
    // fail closed — with the same round-budget/deferred-note handling as the null-response
    // branch above; do not fall through to the severity-floor exit check.
    if (rt.findingsCount > 0 && rt.findings.length === 0) {
      log('WARNING: findingsCount=' + rt.findingsCount + ' but findings array is empty for group ' +
          group.label + ' round ' + uRound + ' — treating as unknown (not clean); preserving last known sig set')
      if (uRound >= 5) {
        log('Findings-count mismatch exceeded round budget for group ' + group.label + ' — deferring')
        await callAgent(
          'Write workspace/todos/deferred/' + wave.waveId + '-group-' + group.label + '-rt-mismatch-budget.md\n\n' +
          'Include: wave ID (' + wave.waveId + '), group (' + group.label + '), date (' + TODAY + '),\n' +
          'round (' + uRound + '), reason: unit redteam agent reported findingsCount=' + rt.findingsCount +
          ' with an empty findings array on every round — unknown state.\n' +
          'Instruction: "Re-run /wave ' + wave.waveId + ' to retry unit redteam for this group."',
          { label: 'defer:unit:' + group.label + ':rt-mismatch-budget', phase: 'Unit Redteam' }
        )
        // RT-003 (this wave, LRN-032; ported from wave-cycle.js): this exit fails closed
        // exactly like the null-response branch above — a findingsCount/findings mismatch
        // on every round is an UNKNOWN verdict, not a clean one; block archive via
        // redteamUnknownBlocked.
        protocolBlocked = true
        redteamUnknownBlocked = true
        break
      }
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

    // RT-001 (ported from wave-cycle.js): codify accumulation MUST happen before the
    // round-budget exit below (and every other exit path from here on) — GH-132's severity
    // floor means reaching the round cap now signals SURVIVING critical/high findings, not a
    // leftover low nit, so they must reach the Codify LRN pass / SDK-issue scan even when the
    // loop is about to give up on this group.
    const highFindings = blocking.filter(function(f) { return f.codify })
    allHighFindings.push.apply(allHighFindings, highFindings)

    // Deferred-exit check before debug — avoids wasting a debug agent call that's immediately
    // abandoned. RT-001: also marks the wave as blocked — reaching this cap means critical/high
    // findings survived every fix attempt, so the wave must not archive as if clean.
    if (uRound >= 5) {
      log('Round budget exhausted for group ' + group.label + ' — deferring and blocking archive (surviving critical/high findings)')
      await callAgent(
        'Write workspace/todos/deferred/' + wave.waveId + '-group-' + group.label + '-budget-exhausted.md\n\n' +
        'Include: wave ID (' + wave.waveId + '), group (' + group.label + '), date (' + TODAY + '),\n' +
        'round count (' + uRound + '), and the final findings:\n' +
        JSON.stringify(rt.findings, null, 2) + '\n\n' +
        'Instruction: "Fix remaining findings, then re-run /wave ' + wave.waveId + '".',
        { label: 'defer:unit:' + group.label, phase: 'Unit Redteam' }
      )
      unitBudgetBlocked = true
      protocolBlocked = true
      break
    }

    // GH-132: debug REPLACES the fix fan-out (rather than running alongside it) at
    // round 4+ (uRound > 3) or on stall — the debug agent already fixes at the root
    // itself (see its prompt below), so also dispatching the fix fan-out in the same
    // round duplicated the fix work and compounded agent cost.
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
      // GH-132: batch into ONE agent covering every file this round unless the
      // round's blocking findings span more files than FIX_BATCH_FILE_THRESHOLD —
      // past that, fall back to the original one-agent-per-file parallel fan-out.
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
                'Run `.venv/bin/pytest -q tests/` (scoped to changed files) after fixing.',
                { label: 'fix:unit:' + group.label + ':r' + uRound + ':' + file.replace(/\//g, '-'),
                  phase: 'Unit Redteam', agentType: 'python-implementer' }
              )
            }
          })
        : [function() {
            return callAgent(
              'Fix these findings, grouped by file:\n\n' +
              JSON.stringify(byFile, null, 2) + '\n\n' +
              'Run `.venv/bin/pytest -q tests/` (scoped to changed files) after fixing.',
              { label: 'fix:unit:' + group.label + ':r' + uRound, phase: 'Unit Redteam', agentType: 'python-implementer' }
            )
          }]

      await parallel(fixTasks)
    }

    const unitGate = await callAgent(
      'Run: .venv/bin/pytest -q tests/\n' +
      'Report: exitCode (0=pass, non-zero=fail), passCount, failCount, and failures (list of\n' +
      '"test_file.py::test_name: reason" for each failing test). Return all fields.',
      { schema: GATE_SCHEMA, label: 'gate:unit:' + group.label + ':r' + uRound, phase: 'Unit Redteam' }
    )
    if (unitGate && unitGate.exitCode !== 0) {
      testsRed = true
      log('Gate RED (' + unitGate.failCount + ' failing) — dispatching test-fix agent')
      await callAgent(
        'Fix the failing tests. Read the test file and the source it covers.\n' +
        'Failing tests:\n' + unitGate.failures.join('\n') + '\n\n' +
        'Run `.venv/bin/pytest -q <failing-test-file>` to confirm GREEN before finishing.',
        { label: 'fix:tests:unit:' + group.label + ':r' + uRound, phase: 'Unit Redteam' }
      )
    }
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
}

// ─── phase 4: phase redteam ───────────────────────────────────────────────────
phase('Phase Redteam')

if (!wave.allScope || wave.allScope.length === 0) {
  log('ERROR: phase redteam aborted — scope (Creates: ∪ Modifies:) is empty (a harness bug, not a clean wave)')
  return { error: 'empty-scope-phase-redteam', waveId: wave.waveId }
}

let pRound   = 0
let prevSigs = new Set()
// RT-009: accumulates every round's non-blocking findings, across ALL loop-exit paths —
// written once, after the loop, regardless of which break fired.
let phaseNonBlocking = []
let phaseNonBlockingSigs = new Set()

while (true) {
  pRound++

  const rt = await callAgent(
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

  // RT-004 (ported from wave-cycle.js): null redteam response is unknown state —
  // must not be treated as clean (fail-open). Do NOT reset prevSigs on null —
  // preserve the last real finding set so stall detection remains valid.
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
      // RT-003 (this wave, LRN-032; ported from wave-cycle.js): mirrors the unit loop's
      // null-response budget fix — an UNKNOWN verdict must block archive at least as hard
      // as one where findings actually survived.
      protocolBlocked = true
      redteamUnknownBlocked = true
      break
    }
    continue
  }

  if (rt.findingsCount === 0 && rt.findings.length > 0) {
    log('WARNING: findingsCount=0 but findings array has ' + rt.findings.length + ' item(s) — treating as non-clean')
    rt.findingsCount = rt.findings.length
  }

  // RT-007 / GH-132 (ported from wave-cycle.js): the inverse mismatch — findingsCount>0
  // with an EMPTY findings array — is schema-valid (RT_SCHEMA sets no minItems) but would
  // break the loop clean on `blocking.length === 0` below, since blocking is derived from
  // rt.findings, not findingsCount. Treat exactly like a null response — unknown state,
  // fail closed — with the same round-budget/deferred-note handling as the null-response
  // branch above; do not fall through to the severity-floor exit check.
  if (rt.findingsCount > 0 && rt.findings.length === 0) {
    log('WARNING: findingsCount=' + rt.findingsCount + ' but findings array is empty at round ' +
        pRound + ' — treating as unknown (not clean)')
    if (pRound >= 8) {
      log('Findings-count mismatch exceeded phase round budget — deferring')
      await callAgent(
        'Write workspace/todos/deferred/' + wave.waveId + '-phase-rt-mismatch-budget.md\n\n' +
        'Include: wave ID (' + wave.waveId + '), date (' + TODAY + '),\n' +
        'round (' + pRound + '), reason: phase redteam agent reported findingsCount=' + rt.findingsCount +
        ' with an empty findings array on every round — unknown state.\n' +
        'Instruction: "Re-run /wave ' + wave.waveId + ' to retry phase redteam."',
        { label: 'defer:phase:rt-mismatch-budget', phase: 'Phase Redteam' }
      )
      // RT-003 (this wave, LRN-032; ported from wave-cycle.js): this exit fails closed
      // exactly like the null-response branch above — an UNKNOWN verdict must block
      // archive via redteamUnknownBlocked.
      protocolBlocked = true
      redteamUnknownBlocked = true
      break
    }
    continue
  }

  // GH-132: severity floor — only critical/high findings block the loop. RT-009:
  // medium/low findings are accumulated (deduped) into phaseNonBlocking every round and
  // written to ONE deferred note after the loop ends — on every exit path, not only when
  // the loop happens to exit clean.
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

  // RT-001 (ported from wave-cycle.js): codify accumulation MUST happen before the
  // round-budget exit below (and every other exit path from here on) — GH-132's severity
  // floor means reaching the round cap now signals SURVIVING critical/high findings, not a
  // leftover low nit, so they must reach the Codify LRN pass / SDK-issue scan even when the
  // loop is about to give up on the whole wave.
  const highFindings = blocking.filter(function(f) { return f.codify })
  allHighFindings.push.apply(allHighFindings, highFindings)

  // Budget-exit check before debug — avoids wasting a debug agent call that's immediately
  // abandoned. RT-001: also marks the wave as blocked and writes a deferred note (mirroring
  // the unit loop's round-budget exit) — reaching this cap means critical/high findings
  // survived every fix attempt across the whole wave, so it must not archive as if clean.
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

  // GH-132: debug REPLACES the fix fan-out (rather than running alongside it) at
  // round 4+ (pRound > 3) or on stall.
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
    // GH-132: batch into ONE agent covering every file this round unless the round's
    // blocking findings span more files than FIX_BATCH_FILE_THRESHOLD.
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
              'Run `.venv/bin/pytest -q tests/` after fixing.',
              { label: 'fix:phase:r' + pRound + ':' + file.replace(/\//g, '-'), phase: 'Phase Redteam',
                agentType: 'python-implementer' }
            )
          }
        })
      : [function() {
          return callAgent(
            'Fix findings, grouped by file:\n\n' + JSON.stringify(byFile, null, 2) + '\n\n' +
            'Run `.venv/bin/pytest -q tests/` after fixing.',
            { label: 'fix:phase:r' + pRound, phase: 'Phase Redteam', agentType: 'python-implementer' }
          )
        }]

    await parallel(fixTasks)
  }

  const phaseGate = await callAgent(
    'Run: .venv/bin/pytest -q tests/\n' +
    'Report: exitCode (0=pass, non-zero=fail), passCount, failCount, and failures. Return all fields.',
    { schema: GATE_SCHEMA, label: 'gate:phase:r' + pRound, phase: 'Phase Redteam' }
  )
  if (phaseGate && phaseGate.exitCode !== 0) {
    testsRed = true
    log('Gate RED (' + phaseGate.failCount + ' failing) — dispatching test-fix agent')
    await callAgent(
      'Fix the failing tests.\n' +
      'Failing tests:\n' + phaseGate.failures.join('\n') + '\n\n' +
      'Run `.venv/bin/pytest -q <failing-test-file>` to confirm GREEN.',
      { label: 'fix:tests:phase:r' + pRound, phase: 'Phase Redteam' }
    )
  }
}

// RT-009: written ONCE, after the loop, from ONE place — covers every exit path (clean,
// null-round budget, findings-mismatch budget, round-budget-exhausted, null-gate,
// tests-red), not only the clean-exit branch that used to write this inline.
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

  const advisorTasks = []

  if (runA2A) {
    advisorTasks.push(function() {
      return callAgent(
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
      return callAgent(
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
    return callAgent(
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

  // RT-001 (round-6 fresh-lens): fail-closed on a null advisor result — see the identical
  // guard in wave-cycle.js. `(await parallel(advisorTasks)).filter(Boolean)` silently
  // DISCARDED a crashed or schema-rejected advisor, so a protocol leg that never produced a
  // verdict contributed 0 to protoCritical/protoHigh and the wave archived as protocol-clean
  // without having been audited. A dropped verdict is UNKNOWN, never clean
  // (LRN-019/022/023/024/026/029/030/031/063).
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
    await callAgent(
      'Fix ALL critical protocol conformance findings below. These block archive.\n\n' +
      'Findings:\n' + JSON.stringify(
        allProtoFindings.filter(function(f) { return f.severity === 'critical' }),
        null, 2
      ) + '\n\n' +
      'Run `.venv/bin/pytest -q tests/` after fixing. Report files changed.',
      { label: 'proto:fix', phase: 'Protocol Audit', agentType: 'python-implementer' }
    )

    const protoFixGate = await callAgent(
      'Run: .venv/bin/pytest -q tests/\n' +
      'Report: exitCode (0=pass, non-zero=fail), passCount, failCount, failures. Return all fields.',
      { schema: GATE_SCHEMA, label: 'gate:proto:fix', phase: 'Protocol Audit' }
    )
    if (protoFixGate && protoFixGate.exitCode !== 0) {
      testsRed = true
      log('Gate RED after proto:fix — dispatching test-fix agent')
      await callAgent(
        'Fix the failing tests introduced by the protocol fix.\n' +
        'Failing tests:\n' + protoFixGate.failures.join('\n') + '\n\n' +
        'Run `.venv/bin/pytest -q <failing-test-file>` to confirm GREEN.',
        { label: 'fix:tests:proto:fix', phase: 'Protocol Audit' }
      )
    }

    const recheckTasks = []
    if (runA2A) {
      recheckTasks.push(function() {
        return callAgent(
          'A2A re-audit after preceding fix.\n' +
          'Scope paths (Creates: ∪ Modifies:):\n' + wave.allScope.join('\n') + '\n' +
          'Focus on previously-critical findings. Return structured findings.',
          { schema: PROTO_SCHEMA, agentType: 'a2a-advisor', label: 'proto:recheck:a2a', phase: 'Protocol Audit' }
        )
      })
    }
    if (runMCP) {
      recheckTasks.push(function() {
        return callAgent(
          'MCP re-audit after preceding fix.\n' +
          'Scope paths (Creates: ∪ Modifies:):\n' + wave.allScope.join('\n') + '\n' +
          'Focus on previously-critical findings. Return structured findings.',
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
    recheckTasks.push(function() {
      return callAgent(
        'Cross-protocol seam re-audit after preceding fix.\n' +
        'Scope paths (Creates: ∪ Modifies:):\n' + wave.allScope.join('\n') + '\n' +
        'Focus on previously-critical SEAM findings. Return structured findings.',
        { schema: PROTO_SCHEMA, label: 'proto:recheck:seam', phase: 'Protocol Audit' }
      )
    })
    // RT-001 (round-6 fresh-lens): fail-closed, same as the initial fan-out above. A null
    // recheck advisor drops the verdict on a protocol that ALREADY had a critical finding,
    // so protoCritical recomputes to 0 and the wave archives as though the fix were verified.
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

// GH-132: hard cap on LRN files captured per wave (MAX_LRN_PER_WAVE, defined above).
// Findings beyond the cap were already fixed by the redteam loops above — only
// individual LRN codification is capped. The SDK issue scan below still classifies
// the FULL toCodeify set.
const lrnCandidates = toCodeify.slice(0, MAX_LRN_PER_WAVE)
if (toCodeify.length > MAX_LRN_PER_WAVE) {
  const overflowLrnCandidates = toCodeify.slice(MAX_LRN_PER_WAVE)
  log('WARNING: ' + toCodeify.length + ' critical/high finding(s) — capping LRN capture at ' +
      MAX_LRN_PER_WAVE + ' per wave (' + overflowLrnCandidates.length +
      ' finding(s) already fixed but not individually codified)')
  // RT-006 (ported from wave-cycle.js): every other truncation/budget path in this file
  // writes a deferred note — this cap dropped findings past MAX_LRN_PER_WAVE with only a
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

if (toCodeify.length > 0) {
  const sdkScan = await callAgent(
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

    await callAgent(
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
}

if (lrnCandidates.length > 0) {
  await parallel(lrnCandidates.map(function(f, i) {
    return function() {
      const lrnNum = lrnBase + i
      const lrnId  = 'LRN-' + String(lrnNum).padStart(3, '0')
      return callAgent(
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

  await callAgent(
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
  await callAgent(
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

const preArchiveGate = await callAgent(
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
// RT-004: step 5's ABSOLUTE and RELATIVE-with-module-path from-import forms now apply the
// SAME four-way on-disk disambiguation (submodule → sub-package → pkg-path-as-module →
// pkg-path-as-package) — previously the ABSOLUTE form had no pkg-path-as-module branch (so
// `from agent_sdk.common.origin import guard_origin` missed the real file) and the RELATIVE-
// with-module-path form had no sub-package branch (so an extracted-but-untracked sub-package
// imported via `from ..common import newsubpkg` resolved to a nonexistent `<pkg-path>.py` and
// was never flagged). Both gaps let a mid-wave extraction slip past the gate undetected.
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
    '6. RT-003 (w036) undeclared-scope check: agent_sdk/**.py files that are TRACKED\n' +
    '   (already existed before this wave) evade every check above if modified but never\n' +
    '   declared — offendingPaths only fires when the path is in the scope list,\n' +
    '   offendingHarnessPaths only watches specific harness dirs (agent_sdk/ is not one),\n' +
    '   and offendingUndeclaredImports only inspects UNTRACKED .py files (`git ls-files`\n' +
    '   empty). For every dirty path from step 2 that (a) matches agent_sdk/**/*.py\n' +
    '   (anywhere under agent_sdk/, .py extension), (b) IS tracked — `git ls-files <path>`\n' +
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

  if (!archiveIntent) {
    protocolBlocked = true
    log('WARNING: archive-commit gate agent returned null — archive BLOCKED (unknown commit state). Re-run /wave ' + wave.waveId)
    // WC-001 mirror: write a durable deferred note so the operator can inspect why archive
    // was blocked even after the console output scrolls away.
    await callAgent(
      'Write workspace/todos/deferred/' + wave.waveId + '-archive-commit-null.md\n\n' +
      'Include: wave ID (' + wave.waveId + '), date (' + TODAY + '),\n' +
      'reason: archive-commit gate agent returned null (unknown working tree state).\n' +
      'Instruction: "Re-run /wave ' + wave.waveId + ' to retry the archive-commit gate."',
      { label: 'defer:archive-commit-null', phase: 'Archive' }
    )
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
      // RT-003 (w036): a tracked agent_sdk/**.py file modified mid-wave but named only in a
      // todo's Reuses:/SI: prose, never added to Creates:/Modifies: — invisible to
      // offendingPaths (undeclared), offendingHarnessPaths (agent_sdk/ is not a harness
      // dir), and offendingUndeclaredImports (untracked-.py-only). Staging without
      // declaring it here loses the paper trail wave.allScope exists to guarantee.
      log('Archive BLOCKED — ' + archiveIntent.offendingUndeclaredScope.length + ' tracked source file(s) are modified but undeclared:')
      archiveIntent.offendingUndeclaredScope.forEach(function(p) { log('  [undeclared scope] ' + p) })
      log('Add the file(s) above to Creates:/Modifies: in the wave/todo, then re-run /wave ' + wave.waveId)
    }
    log('Commit or stage the files above, then re-run /wave ' + wave.waveId)
  } else {
    log('Commit check passed — all scope files and harness deliverables are committed')
  }

  // RT-004 (LRN-131; GH-131/GH-132/LRN-071/LRN-085): hard-block archive when this wave declares
  // a template/ deliverable but template/ is not checked out in this working tree — independent
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
    // RT-004 (LRN-131): distinct from the generic protocol-findings message below — this wave
    // is blocked because template/ propagation is unverifiable, not a protocol audit finding.
    // /agent-verify would not fix this; checking out template/ would.
    log('Archive SKIPPED — wave ' + wave.waveId + ' declares a template/ deliverable but template/ is not checked out (see ARCHIVE BLOCKED detail above).')
    log('Clone wailuen/a2a-agent-template into template/, land the propagated file(s), then re-run /wave ' + wave.waveId + '.')
  } else if (redteamUnknownBlocked) {
    // RT-003 (this wave, LRN-032; ported from wave-cycle.js): distinct from the generic
    // protocol-findings message below — this wave is blocked because a redteam round budget
    // was exhausted while the verdict itself was never established (persistent null
    // response, or a findingsCount/findings mismatch), not because critical/high findings
    // actually survived review. /agent-verify would not fix this; obtaining a trustworthy
    // redteam verdict would.
    log('Archive SKIPPED — wave ' + wave.waveId + ' blocked: redteam never returned a trustworthy verdict (persistent null response or findingsCount mismatch) within its round budget.')
    log('See the workspace/todos/deferred/' + wave.waveId + '-*-rt-null-budget.md / -rt-mismatch-budget.md note(s), then re-run /wave ' + wave.waveId + '.')
  } else if (phaseBudgetBlocked) {
    // RT-001 (ported from wave-cycle.js): distinct from the generic protocol-findings message
    // below — this wave is blocked because the phase redteam round budget was exhausted with
    // surviving critical/high findings, not a protocol audit finding. /agent-verify would not
    // fix this; fixing the findings in the deferred note would.
    log('Archive SKIPPED — wave ' + wave.waveId + ' blocked: phase redteam round budget exhausted with surviving critical/high findings.')
    log('Fix the findings in workspace/todos/deferred/' + wave.waveId + '-phase-budget-exhausted.md, then re-run /wave ' + wave.waveId + '.')
  } else if (unitBudgetBlocked) {
    // RT-001 (ported from wave-cycle.js): mirrors phaseBudgetBlocked above, for a per-group
    // unit redteam round budget exhausted with surviving critical/high findings.
    log('Archive SKIPPED — wave ' + wave.waveId + ' blocked: unit redteam round budget exhausted with surviving critical/high findings for at least one group.')
    log('Fix the findings in the affected group\'s workspace/todos/deferred/' + wave.waveId + '-group-<label>-budget-exhausted.md, then re-run /wave ' + wave.waveId + '.')
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
    '   If Implementation: says [pending], replace with the real path:symbol.\n' +
    '   Scope paths (Creates: ∪ Modifies:):\n' + wave.allScope.join('\n') + '\n\n' +
    'Report: file moved (or the collision reported instead), plan.md updated (row updated or\n' +
    'appended), FR fields updated.',
    { label: 'archive', phase: 'Archive' }
  )

  log('Wave ' + wave.waveId + ' archived — ' + lrnCandidates.length + ' LRN(s) captured')
}

return {
  waveId:             wave.waveId,
  totalTodos:         totalTodos,
  lrnsCaptured:       lrnCandidates.length,
  cNnnRegistered:     registryCandidates.length,
  sdkCandidates:      sdkCandidatesCount,
  groupsExecuted:     wave.groups.length,
  phaseRedteamRounds: pRound,
  exhausted:          pRound >= 8,
  protocolBlocked:    protocolBlocked,
  testsRed:           testsRed,
  redteamUnknownBlocked: redteamUnknownBlocked,  // RT-003 (this wave, LRN-032): a redteam round budget was exhausted with the verdict itself never established (null response or findingsCount mismatch)
  unitBudgetBlocked:  unitBudgetBlocked,   // RT-001 (ported from wave-cycle.js): a group's unit redteam round budget was exhausted with surviving critical/high findings
  phaseBudgetBlocked: phaseBudgetBlocked,  // RT-001 (ported from wave-cycle.js): the phase redteam round budget was exhausted with surviving critical/high findings
}
