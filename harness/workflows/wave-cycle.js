export const meta = {
  name: 'wave-cycle',
  description: 'Execute one wave: deterministic preflight + parse → todos plan review until zero issues (planner fixes rounds 1-3, fresh-lens debug fixes round 4+, 8-round ceiling blocks the wave) → fan-out implement per group → unit zero-tolerance redteam (max 5 rounds; debug replaces the fix fan-out at round 4+ or on stall) → phase zero-tolerance redteam (max 8 rounds; same debug rule) → protocol audit → codify LRNs + register new C-NNN components → deterministic archive gate → archive',
  phases: [
    { title: 'Parse',          detail: 'One scripted preflight (repo layout, wave-ID collision, concurrent wave, behind origin, scope scan, next LRN), then read the wave file into groups' },
    { title: 'Todos Redteam',  detail: 'Review the plan until zero issues: rounds 1-3 fixed by planner, round 4+ by a fresh-lens debug pass; 8 rounds without a clean review stops the wave before Implement' },
    { title: 'Implement',      detail: 'Fan out todos per group in dependency order; a todo whose agent dies is retried once, then blocks archive' },
    { title: 'Unit Redteam',   detail: 'Per-group zero-tolerance fix loop (max 5 rounds/group; debug replaces the fix fan-out at round 4+ or when the same findings repeat)' },
    { title: 'Phase Redteam',  detail: 'Full-wave zero-tolerance fix loop (max 8 rounds; debug replaces the fix fan-out at round 4+ or when the same findings repeat)' },
    { title: 'Protocol Audit', detail: 'A2A/MCP/AG-UI/A2UI conformance — parallel advisors + seam check (protocol-surface waves only)' },
    { title: 'Codify',         detail: 'SDK issue scan → batched LRN capture for critical/high findings → README index → C-NNN registration' },
    { title: 'Archive',        detail: 'Pytest gate + scripted commit check, then move wave file to completed/, update plan.md, backfill FR Implementation: and Test: fields, verify the move and ledger row' },
  ],
}

// ─── args ─────────────────────────────────────────────────────────────────────
// args.waveFile    : path to the active wave file
// args.today       : ISO date string for plan.md timestamps (the sandbox bans Date)
// args.agentBudget : optional positive override of the per-wave agent-call ceiling
// args.autoFileSdkIssues : optional boolean (default false); true files still-open SDK candidates
//                    on wailuen/a2a-sdk at codify (deduped, capped at 10, redacted)
// args may arrive JSON-encoded as a string; fail fast naming whatever is missing.
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
const WAVE_BASENAME = WAVE_FILE.split('/').pop()
const WAVE_ID_FROM_FILE = (WAVE_BASENAME.match(/^w\d+/) || [WAVE_BASENAME])[0]

// ─── protocol surface paths (trigger the Protocol Audit phase) ─────────────────
// This runner serves downstream agent repos, whose source root is src/. Every auth file
// that require_identity depends on is folded into the three transport surfaces:
// over-triggering an audit is cheap, an unaudited auth change is not. A2UI has no transport
// of its own (it rides A2A DataParts / AG-UI CUSTOM events), so it does not fold auth in.
const AUTH_SURFACE = ['src/routes/oauth', 'src/auth/middleware', 'src/auth/oauth_tokens', 'src/auth/api_keys', 'src/auth/identity', 'src/auth/oidc']
const A2A_SURFACE  = ['src/routes/a2a', 'src/routes/agent_card', 'src/models/a2a'].concat(AUTH_SURFACE)
const MCP_SURFACE  = ['src/routes/mcp'].concat(AUTH_SURFACE)
const AGUI_SURFACE = ['src/routes/ag_ui'].concat(AUTH_SURFACE)
const A2UI_SURFACE = ['src/a2ui/', 'src/models/content_types']

// Test command. Agent repos keep their dependencies in .venv; fall back to the ambient
// python where there is none. One constant, so a repo that needs a different runner
// patches exactly one line.
const PYTEST = '$(test -x .venv/bin/python && echo .venv/bin/python || echo python) -m pytest -q'

// ─── schemas ──────────────────────────────────────────────────────────────────

// Filled verbatim from the preflight script's JSON (see PREFLIGHT_PY below).
const PREFLIGHT_SCHEMA = {
  type: 'object',
  required: ['ok', 'error', 'scopePaths', 'todoFacts'],
  additionalProperties: false,
  properties: {
    ok:                       { type: 'boolean' },
    error:                    { type: 'string' },
    wrongRunnerForRepoLayout: { type: 'boolean' },
    completedFileExists:      { type: 'boolean' },
    templateDirExists:        { type: 'boolean' },
    otherActiveWaves:         { type: 'array', items: { type: 'string' } },
    dirtyPathCount:           { type: 'integer' },
    behindCount:              { type: 'integer' },
    lrnNext:                  { type: 'integer' },
    scopePaths:               { type: 'array', items: { type: 'string' }, description: 'The JSON list printed by the scope scan, unmodified' },
    todoFacts: {
      type: 'array',
      description: 'The JSON list printed by the todo scan, unmodified',
      items: {
        type: 'object',
        required: ['id', 'dependsText', 'held'],
        additionalProperties: false,
        properties: { id: { type: 'string' }, dependsText: { type: 'array', items: { type: 'string' } }, held: { type: 'boolean' } },
      },
    },
  },
}

const WAVE_SCHEMA = {
  type: 'object',
  required: ['waveId', 'allCreates', 'allModifies', 'groups', 'groupDeps'],
  additionalProperties: false,
  properties: {
    waveId:      { type: 'string' },
    allCreates:  { type: 'array', items: { type: 'string' }, description: 'Every in-repo file path this wave creates, from every Creates: line, backticked or bare, outside any "modifies ..." clause.' },
    allModifies: { type: 'array', items: { type: 'string' }, description: 'Every in-repo file path this wave modifies: Modifies: lines plus every path inside a "modifies ..." clause on a Creates: line.' },
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
        required: ['id', 'severity', 'file', 'line', 'quote', 'description', 'fix'],
        additionalProperties: false,
        properties: {
          id:           { type: 'string' },
          severity:     { type: 'string', enum: ['critical', 'high', 'medium', 'low'] },
          file:         { type: 'string' },
          line:         { type: 'integer' },
          quote:        { type: 'string' },
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
    issuesFound: { type: 'boolean', description: 'true when any of reuseAnnotations, siAnnotations, sliceIssues or peerRepoAnnotations is non-empty' },
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
        required: ['id', 'quote', 'description', 'severity', 'component', 'rationale'],
        additionalProperties: false,
        properties: {
          id:          { type: 'string' },
          quote:       { type: 'string' },
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

// Post-archive verification: the ledger row must name this wave's own file (two waves can
// share a waveId), and the wave file must actually have moved.
const ARCHIVE_CHECK_SCHEMA = {
  type: 'object',
  required: ['rowPresent', 'matchCount', 'archivedFileExists', 'activeFileExists'],
  additionalProperties: false,
  properties: {
    rowPresent:         { type: 'boolean' },
    matchCount:         { type: 'number' },
    archivedFileExists: { type: 'boolean' },
    activeFileExists:   { type: 'boolean' },
  },
}

// Filled verbatim from the archive-gate script's JSON (see ARCHIVE_GATE_PY below).
const ARCHIVE_INTENT_SCHEMA = {
  type: 'object',
  required: ['ok', 'error'],
  additionalProperties: false,
  properties: {
    ok:                         { type: 'boolean' },
    error:                      { type: 'string' },
    dirtyPaths:                 { type: 'array', items: { type: 'string' } },
    offendingPaths:             { type: 'array', items: { type: 'string' }, description: 'Uncommitted paths inside the wave scope' },
    offendingHarnessPaths:      { type: 'array', items: { type: 'string' }, description: 'Uncommitted harness deliverables, incl. template/.claude/workflows/ mirror changes or unpushed template commits' },
    offendingUndeclaredImports: { type: 'array', items: { type: 'string' }, description: 'Untracked, undeclared src modules imported by scope or dirty .py files' },
    offendingUndeclaredScope:   { type: 'array', items: { type: 'string' }, description: 'Tracked src/**.py files modified but not declared in scope' },
    templateDirExists:          { type: 'boolean' },
  },
}
const ARCHIVE_INTENT_LISTS = ['dirtyPaths', 'offendingPaths', 'offendingHarnessPaths', 'offendingUndeclaredImports', 'offendingUndeclaredScope']

// ─── deterministic scripts (run by an agent, results returned verbatim) ───────

// Preflight: every Parse-phase fact that is a file-system or git lookup, in one run.
// Failure of the fetch (no remote, offline) is not a blocker; failure of git itself is.
const PREFLIGHT_PY = [
  'import json,os,re,subprocess,sys',
  'def run(*a):',
  '    try:',
  '        r=subprocess.run(a,capture_output=True,text=True,timeout=120)',
  '        return r.stdout if r.returncode==0 else None',
  '    except Exception:',
  '        return None',
  'base=os.path.basename(sys.argv[1])',
  'top=run("git","rev-parse","--show-toplevel")',
  'if top is None:',
  '    print(json.dumps({"ok":False,"error":"not inside a git repository"}))',
  '    sys.exit(0)',
  'os.chdir(top.strip())',
  'act="workspace/todos/active"',
  'others=sorted(f for f in (os.listdir(act) if os.path.isdir(act) else []) if re.match(r"w\\d+-.*\\.md$",f) and f!=base)',
  'st=run("git","status","--porcelain")',
  'dirty=len([l for l in st.splitlines() if l.strip()]) if st is not None else -1',
  'run("git","fetch","origin","main","--quiet")',
  'b=run("git","rev-list","--count","main..origin/main")',
  'behind=int(b.strip()) if b and b.strip().isdigit() else 0',
  'learn="workspace/learning"',
  'nums=[int(n) for f in (os.listdir(learn) if os.path.isdir(learn) else []) for n in re.findall(r"^LRN-(\\d+)",f)]',
  'idx=os.path.join(learn,"README.md")',
  'if os.path.isfile(idx): nums+=[int(n) for n in re.findall(r"LRN-(\\d+)",open(idx,encoding="utf-8").read())]',
  'print(json.dumps({"ok":True,"error":"",',
  '  "wrongRunnerForRepoLayout":os.path.isdir("agent_sdk") and not os.path.isdir("src"),',
  '  "completedFileExists":os.path.exists("workspace/todos/completed/"+base),',
  '  "templateDirExists":os.path.isdir("template"),',
  '  "otherActiveWaves":others,"dirtyPathCount":dirty,"behindCount":behind,',
  '  "lrnNext":max(nums,default=0)+1}))',
].join('\n')

// Archive commit gate. Blocks archive when anything the wave produced would be lost on
// checkout or would break on a fresh clone:
//   offendingPaths             uncommitted scope files
//   offendingHarnessPaths      uncommitted harness deliverables (tests/, docs/, workflows,
//                              agents, skills, prd/learning/results, pyproject.toml), plus the
//                              template/ peer repo's workflow mirror when dirty or unpushed —
//                              template/ is a nested repo the top-level git status cannot see
//   offendingUndeclaredImports untracked src modules that a scope/dirty .py file imports
//                              (absolute src.* or relative), resolved on disk with ast
//   offendingUndeclaredScope   tracked src/**.py files modified but not declared (exact match)
const ARCHIVE_GATE_PY = [
  'import ast,json,os,subprocess,sys',
  'def git(*a):',
  '    r=subprocess.run(("git",)+a,capture_output=True,text=True)',
  '    if r.returncode!=0: raise RuntimeError("git "+" ".join(a)+": "+r.stderr.strip())',
  '    return r.stdout',
  'def norm(p): return os.path.normpath(p).replace(os.sep,"/")',
  'def paths(raw):',
  '    out=[]',
  '    for l in raw.splitlines():',
  '        if len(l)>3: out.append((l[:2],norm(l[3:].split(" -> ")[-1].strip().strip(chr(34)))))',
  '    return out',
  'def under(p,d): return p==d or p.startswith(d.rstrip("/")+"/")',
  'def first(*c):',
  '    for x in c:',
  '        if os.path.isfile(x): return norm(x)',
  '    return None',
  'try:',
  '    os.chdir(git("rev-parse","--show-toplevel").strip())',
  '    scope={norm(p) for p in json.loads(sys.argv[1])}',
  '    status=paths(git("status","--porcelain","-uall"))',
  '    dirty=[p for _,p in status]',
  '    tracked={norm(p) for p in git("ls-files").splitlines()}',
  '    offending=[p for p in dirty if any(under(p,s) or under(s,p) for s in scope)]',
  '    hdirs=("tests/","docs/","workspace/learning/","workspace/scenarios/results/","workspace/prd/",".claude/workflows/","harness/workflows/",".claude/agents/","harness/agents/",".claude/skills/","harness/skills/")',
  '    harness=[p for p in dirty if p.startswith(hdirs) or p=="pyproject.toml"]',
  '    if os.path.exists("template/.git"):',
  '        harness+=["template/"+p for _,p in paths(git("-C","template","status","--porcelain","-uall")) if p.startswith(".claude/workflows/")]',
  '        r=subprocess.run(["git","-C","template","merge-base","--is-ancestor","HEAD","origin/main"],capture_output=True,text=True)',
  '        if r.returncode!=0: harness.append("template/ (unpushed or not on origin/main: merge a template PR)")',
  '    targets=set()',
  '    for f in sorted({p for p in dirty+list(scope) if p.endswith(".py")}):',
  '        if not os.path.isfile(f): continue',
  '        try: tree=ast.parse(open(f,encoding="utf-8").read())',
  '        except Exception: continue',
  '        for n in ast.walk(tree):',
  '            if isinstance(n,ast.Import):',
  '                for a in n.names:',
  '                    if a.name=="src" or a.name.startswith("src."):',
  '                        m=a.name.replace(".","/")',
  '                        targets.add(first(m+".py",m+"/__init__.py"))',
  '            elif isinstance(n,ast.ImportFrom):',
  '                if n.level==0:',
  '                    if not n.module or not (n.module=="src" or n.module.startswith("src.")): continue',
  '                    pkg=n.module.replace(".","/"); named=n.module!="src"',
  '                else:',
  '                    base=os.path.dirname(f)',
  '                    for _ in range(n.level-1): base=os.path.dirname(base)',
  '                    pkg=norm(os.path.join(base,(n.module or "").replace(".","/")))',
  '                    named=bool(n.module)',
  '                for a in n.names:',
  '                    c=[pkg+"/"+a.name+".py",pkg+"/"+a.name+"/__init__.py"] if a.name!="*" else []',
  '                    if named: c.append(pkg+".py")',
  '                    c.append(pkg+"/__init__.py")',
  '                    targets.add(first(*c))',
  '    imports=sorted(t for t in targets if t and t not in tracked and t not in scope)',
  '    undeclared=[p for p in dirty if p.startswith("src/") and p.endswith(".py") and p in tracked and p not in scope]',
  '    print(json.dumps({"ok":True,"error":"","dirtyPaths":dirty,"offendingPaths":offending,',
  '      "offendingHarnessPaths":harness,"offendingUndeclaredImports":imports,',
  '      "offendingUndeclaredScope":undeclared,"templateDirExists":os.path.isdir("template")}))',
  'except Exception as e:',
  '    print(json.dumps({"ok":False,"error":str(e)}))',
].join('\n')

// Deterministic Creates:/Modifies: scope scan — the ground truth Parse is checked against.
// Keep its path rule in step with harness/wave_scope.py::_looks_like_path.
const SCOPE_SCAN_PY = [
  'import json,re,sys',
  'EXT=(".py",".js",".ts",".md",".json",".toml",".yaml",".yml",".lock")',
  'ROOT=(".md",".json",".toml",".yaml",".yml",".lock")',
  'DOT={".env.example",".env.sample",".env.template",".gitignore",".gitattributes",".dockerignore",".editorconfig",".python-version",".nvmrc",".npmrc",".pre-commit-config.yaml"}',
  'BAD=" ()"+chr(34)+chr(39)',
  'def ok(t):',
  '    if not t or any(c in t for c in BAD) or "*" in t or "?" in t: return False',
  '    if t.startswith("/") or t.endswith("/") or t.startswith("template/"): return False',
  '    f=t.rsplit("/",1)[-1]',
  '    if f.startswith("."): return f in DOT',
  '    if "/" not in t: return "__" not in t and f.endswith(ROOT)',
  '    return f.endswith(EXT)',
  'out=[]; skip=False',
  'for l in open(sys.argv[1],encoding="utf-8"):',
  '    if re.match(r"\\s*(?:[-*]\\s*)?(?:#{1,6}\\s|\\[.\\])",l): skip="[~]" in l',
  '    if skip or not re.match(r"\\s*(?:[-*+]\\s*)?(?:\\*\\*)?(?:Creates|Modifies)(?:\\*\\*)?:",l,re.I): continue',
  '    for t in re.split(r"[\\s,;()\\[\\]]+",l):',
  '        t=t.lstrip("`*"+chr(34)+chr(39)).rstrip("`*.,:;"+chr(34)+chr(39))',
  '        if ok(t): out.append(t)',
  'print(json.dumps(sorted(set(out))))',
].join('\n')

// Deterministic todo facts, read from the wave file itself (never from the model's relay of it):
// per todo id, the raw text after each "Depends:" and whether an unreleased HUMAN GATE marker
// holds it. Todos marked [~] are skipped, matching the scope scan.
const TODO_SCAN_PY = [
  'import json,re,sys',
  'TODO=re.compile(r"^\\s*[-*+]\\s*\\[(.)\\]\\s*"+chr(96)+r"([^"+chr(96)+r"]+)"+chr(96))',
  'GATE=re.compile(r"^\\s*(?:[-*+]\\s*)?(?:\\*\\*)?HUMAN GATE(?:\\*\\*)?\\s*:",re.M)',
  'REL=re.compile(r"^\\s*(?:[-*+]\\s*)?(?:\\*\\*)?Release(?:\\*\\*)?\\s*:(?:\\*\\*)?[^\\n]*https://github\\.com/[\\w.-]+/[\\w.-]+/issues/\\d+",re.I|re.M)',
  'out=[]; cur=None',
  'def flush():',
  '    if cur is None or cur["skip"]: return',
  '    body="".join(cur["lines"])',
  '    dep=[m.group(1).strip() for l in cur["lines"] for m in [re.search(r"Depends:(?:\\*\\*)?\\s*(.*)$",l,re.I)] if m]',
  '    out.append({"id":cur["id"],"dependsText":dep,"held":bool(GATE.search(body)) and not REL.search(body)})',
  'for l in open(sys.argv[1],encoding="utf-8"):',
  '    m=TODO.match(l)',
  '    if m:',
  '        flush(); cur={"id":m.group(2).strip(),"skip":m.group(1)=="~","lines":[]}; continue',
  '    if re.match(r"\\s*#{1,6}\\s",l):',
  '        flush(); cur=None; continue',
  '    if cur is not None: cur["lines"].append(l)',
  'flush()',
  'print(json.dumps(out))',
].join('\n')

function shq(s) { return "'" + String(s).replace(/'/g, "'\\''") + "'" }

// Shared path rule for the deliverable gate: the scope scan's own head (EXT/ROOT/DOT lists and
// ok()), sliced from SCOPE_SCAN_PY so there is exactly one path classifier in this runner.
const PATH_RULE_PY = SCOPE_SCAN_PY.slice(0, SCOPE_SCAN_PY.indexOf('\nout=[]; skip=False'))

// Deliverable gate: one run per Implement tier. A concrete Creates: path must exist; an
// acceptance record (workspace/acceptance/*.md) must also carry a FIRST verdict of PASS (heading
// form or "Verdict: X" line form) and no "[pending"; a pattern path (glob, or a planner
// placeholder such as LRN-NNN / run-NNN / C-NNN) needs a match newer than Implement start. A
// missing or malformed "since" counts every pattern path as missing.
const DELIVERABLE_GATE_PY = PATH_RULE_PY + '\n' + [
  'import os,glob',
  'spec=json.loads(sys.argv[1])',
  's=spec.get("since")',
  'since=float(s) if isinstance(s,(int,float)) and not isinstance(s,bool) else None',
  'PH=re.compile(r"(?<![A-Za-z])N{3,}(?![A-Za-z])")',
  'V=re.compile(r"^[\\s>*_-]*(?:#+[\\s*_]*)?verdict\\b[\\s*_]*:?[\\s*_]*([A-Za-z]*)",re.I)',
  'def has_ph(t): return PH.search(t) is not None',
  'def pat(t): return ("*" in t or "?" in t or has_ph(t)) and ok(PH.sub("0",t).replace("*","x").replace("?","x"))',
  'def concrete(t): return ok(t) and not has_ph(t)',
  'def gl(t): return PH.sub("[0-9]*",t)',
  'def record(p): return p.startswith("workspace/acceptance/") and p[-3:]==".md"',
  'def verdict(s):',
  '    ls=s.splitlines()',
  '    for i,l in enumerate(ls):',
  '        m=V.match(l)',
  '        if not m: continue',
  '        if m.group(1): return m.group(1).upper()',
  '        for n in ls[i+1:]:',
  '            if n.strip():',
  '                k=re.match(r"^[\\s>*_-]*([A-Za-z]+)",n)',
  '                return k.group(1).upper() if k else ""',
  '        return ""',
  '    return ""',
  'def good(p):',
  '    if not os.path.isfile(p): return False',
  '    if not record(p): return True',
  '    s=open(p,encoding="utf-8",errors="replace").read()',
  '    return verdict(s)=="PASS" and "[pending" not in s.lower()',
  'def fresh(g): return since is not None and any(os.path.isfile(m) and os.path.getmtime(m)>since for m in glob.glob(g,recursive=True))',
  'bad=[]',
  'for label,paths in spec["groups"].items():',
  '    miss=[p for p in paths if (concrete(p) and not good(p)) or (pat(p) and not fresh(gl(p)))]',
  '    if miss: bad.append({"label":label,"paths":miss})',
  'print(json.dumps({"ok":True,"checked":sorted(spec["groups"]),"missing":bad}))',
].join('\n')

const DELIVERABLE_SCHEMA = {
  type: 'object',
  required: ['ok', 'checked', 'missing'],
  additionalProperties: false,
  properties: {
    ok:      { type: 'boolean' },
    error:   { type: 'string' },
    checked: { type: 'array', items: { type: 'string' } },
    missing: {
      type: 'array',
      items: {
        type: 'object',
        required: ['label', 'paths'],
        additionalProperties: false,
        properties: { label: { type: 'string' }, paths: { type: 'array', items: { type: 'string' } } },
      },
    },
  },
}

const SCOPE_RESCAN_SCHEMA = {
  type: 'object',
  required: ['paths'],
  additionalProperties: false,
  properties: { paths: { type: 'array', items: { type: 'string' }, description: 'The JSON list printed by the scope scan, unmodified' } },
}

// A HUMAN GATE todo holds its group until a release line cites a GitHub issue URL. The hold
// comes from TODO_SCAN_PY (a script reading the wave file), stamped on each group by parseWave.
function groupIsHeld(g) {
  return g.held === true
}

// Group deps derived from each todo's Depends: text as read by TODO_SCAN_PY, unioned with the
// model's groupDeps.
function deriveGroupDeps(w) {
  const owner = {}
  w.groups.forEach(function(g) { g.todos.forEach(function(t) { owner[t.id] = g.label }) })
  const ids = Object.keys(owner)
  const found = {}
  w.groups.forEach(function(g) { found[g.label] = new Set((w.groupDeps && w.groupDeps[g.label]) || []) })
  ;(w.todoFacts || []).forEach(function(f) {
    const mine = owner[f.id]
    if (mine === undefined) return
    f.dependsText.forEach(function(text) {
      ids.forEach(function(id) {
        if (owner[id] === mine) return
        const esc = id.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
        if (new RegExp('(^|[^A-Za-z0-9_-])' + esc + '($|[^A-Za-z0-9_-])').test(text)) found[mine].add(owner[id])
      })
    })
  })
  const out = {}
  w.groups.forEach(function(g) { out[g.label] = Array.from(found[g.label]) })
  return out
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

// Severity floor: only critical/high keep a fix loop going; medium/low are recorded in a
// deferred note. The two sets are complements and only the non-blocking one is an
// allow-list, so a missing or unexpected severity blocks (fail-closed) and is named.
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

// Every round's non-blocking findings, deduped by file+description, written once after the
// loop whichever way it exits.
function accumulateNonBlocking(store, seenSigs, findings) {
  for (const f of nonBlockingFindings(findings)) {
    const sig = f.file + ':' + f.description
    if (!seenSigs.has(sig)) {
      seenSigs.add(sig)
      store.push(f)
    }
  }
}

function uniq(xs) { return Array.from(new Set(xs || [])) }

// One fix agent per round covering every file, unless the findings span more files than
// this — then one agent per file, so a single prompt never loses per-file fidelity.
const FIX_BATCH_FILE_THRESHOLD = 6

// Cap on LRN files captured per wave; the overflow is recorded in a deferred note.
const MAX_LRN_PER_WAVE = 20

// Plan review stops the wave if it is not clean after this many rounds.
const PLAN_MAX_ROUNDS = 8
const UNIT_MAX_ROUNDS = 5
const PHASE_MAX_ROUNDS = 8

// ─── agent-call budget (hard backstop) ────────────────────────────────────────
// Every dispatched agent call counts against a per-wave ceiling; exceeding it stops the wave
// loudly with a deferred note. The ceiling scales with the wave's group count once Parse
// resolves it; args.agentBudget overrides it and must be a finite positive number.
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
let lastDispatchedLabel = 'none'
let lastDispatchedPhase = 'Parse'
let waveIdForBudgetNote = WAVE_ID_FROM_FILE
const _dispatchAgent = agent
// All agents share ONE working tree; a stash/reset by one silently deletes other groups'
// uncommitted work. Appended to every prompt.
const SHARED_TREE_GIT_BAN =
  '\n\nSHARED WORKING TREE RULE: other agents have uncommitted work in this tree. NEVER run\n' +
  '`git stash`, `git reset`, `git checkout -- <path>`, `git restore`, `git clean` or\n' +
  '`git checkout .`. Edit files in place. To inspect old content use `git show` / `git diff`.'
async function callAgent(prompt, opts) {
  agentCallCount++
  if (agentCallCount > AGENT_CALL_BUDGET) {
    log('BUDGET EXCEEDED: ' + agentCallCount + ' agent call(s) dispatched this wave — hard budget is ' +
        AGENT_CALL_BUDGET + '. Stopping loudly to prevent runaway cost; investigate the loop or ' +
        'finding volume that drove this before re-running.')
    // Dispatched directly so the note cannot be blocked by the budget it reports on.
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
      { label: 'defer:agent-budget-exceeded', phase: lastDispatchedPhase, effort: 'low' }
    )
    throw new Error('agent-call budget exceeded (' + AGENT_CALL_BUDGET + ' calls) for this wave')
  }
  lastDispatchedLabel = (opts && opts.label) || lastDispatchedLabel
  lastDispatchedPhase = (opts && opts.phase) || lastDispatchedPhase
  return _dispatchAgent(prompt + SHARED_TREE_GIT_BAN, opts)
}

// Deferred notes are mechanical writes. A note that fails to write is logged; the blocking
// flag that motivated it is already set by the caller.
async function deferNote(fileName, body, label, phaseName) {
  const r = await callAgent(
    'Write workspace/todos/deferred/' + fileName + '\n\n' + body,
    { label: label, phase: phaseName, effort: 'low' }
  )
  if (!r) log('WARNING: deferred note workspace/todos/deferred/' + fileName + ' was not written (agent returned null)')
  return r
}

function runGate(label, phaseName) {
  return callAgent(
    'Run: ' + PYTEST + '\n' +
    'Report: exitCode (0=pass, non-zero=fail), passCount, failCount, and failures (list of\n' +
    '"test_file.py::test_name: reason" strings for each failing test). Return all fields.',
    { schema: GATE_SCHEMA, label: label, phase: phaseName, effort: 'low' }
  )
}

// Gate → (red: one test-fix agent → re-gate). Returns 'green', 'null' (gate never reported:
// unknown state, never clean) or 'red' (still red, or unknown, after the test fix).
async function gateWithTestFix(labelBase, phaseName, fixContext) {
  const gate = await runGate('gate:' + labelBase, phaseName)
  if (!gate) {
    log('WARNING: gate ' + labelBase + ' returned null — treating as failure (unknown test state)')
    testsRed = true
    return 'null'
  }
  if (gate.exitCode === 0) return 'green'
  testsRed = true
  log('Gate RED (' + gate.failCount + ' failing) — dispatching test-fix agent')
  await callAgent(
    'Fix the failing tests below' + (fixContext ? ' ' + fixContext : '') + '. Read the test file and the source it covers.\n' +
    'Failing tests:\n' + (gate.failures || []).join('\n') + '\n\n' +
    'Run `' + PYTEST + ' <failing-test-file>` to confirm GREEN before finishing.',
    { label: 'fix:tests:' + labelBase, phase: phaseName }
  )
  const reGate = await runGate('gate:' + labelBase + ':recheck', phaseName)
  if (!reGate || reGate.exitCode !== 0) {
    log('Re-gate still RED (' + (reGate ? reGate.failCount : '?') + ' failing) after test-fix')
    return 'red'
  }
  return 'green'
}

// ─── state ────────────────────────────────────────────────────────────────────
let registryCandidates = []   // new C-NNN candidates from Todos Redteam → registered in Codify
let protocolBlocked        = false   // any cause: archive must not run
let testsRed               = false
let testsBlockedArchive    = false   // pre-archive gate red or unknown
let fixLoopTestsBlocked    = false   // a redteam fix loop stopped on a red/unknown test gate with findings unresolved
let archivePlanRowMissing  = false   // plan.md ledger row (or the move itself) missing after archive
let templatePropagationBlocked = false
let unitBudgetBlocked      = false   // unit round budget exhausted with surviving critical/high findings
let phaseBudgetBlocked     = false   // phase round budget exhausted with surviving critical/high findings
let redteamUnknownBlocked  = false   // a redteam never returned a trustworthy verdict
let implementBlocked       = false   // an implement agent died twice on the same todo
let deliverablesBlocked    = false   // a group's Creates: deliverables are missing/unverified, or a group is held at a HUMAN GATE
let totalTodos             = 0
let sdkCandidatesCount     = 0
const allHighFindings      = []      // critical/high findings → Codify

// ─── phase 0: parse wave file ─────────────────────────────────────────────────
phase('Parse')

async function runPreflight(label) {
  const pf = await callAgent(
    'Run the three commands below at the repo root exactly as written (do not edit them).\n' +
    'Return the JSON object the first one prints, field for field, set scopePaths to the\n' +
    'JSON list the second one prints, unmodified, and set todoFacts to the JSON list the third\n' +
    'one prints, unmodified. If a command fails to run, set ok=false and\n' +
    'put its error text in error.\n\n' +
    'python3 - ' + shq(WAVE_FILE) + " <<'PREFLIGHT'\n" + PREFLIGHT_PY + '\nPREFLIGHT\n\n' +
    'python3 - ' + shq(WAVE_FILE) + " <<'SCOPE_SCAN'\n" + SCOPE_SCAN_PY + '\nSCOPE_SCAN\n\n' +
    'python3 - ' + shq(WAVE_FILE) + " <<'TODO_SCAN'\n" + TODO_SCAN_PY + '\nTODO_SCAN',
    { schema: PREFLIGHT_SCHEMA, label: label, phase: 'Parse', effort: 'low' }
  )
  // Unknown state is never "nothing found": a failed or malformed preflight stops the wave.
  const wellFormed = pf && pf.ok === true &&
    Array.isArray(pf.scopePaths) && Array.isArray(pf.otherActiveWaves) &&
    Array.isArray(pf.todoFacts) && pf.todoFacts.every(function(f) {
      return f && typeof f.id === 'string' && typeof f.held === 'boolean' &&
        Array.isArray(f.dependsText) && f.dependsText.every(function(d) { return typeof d === 'string' })
    }) &&
    ['wrongRunnerForRepoLayout', 'completedFileExists', 'templateDirExists'].every(function(k) { return typeof pf[k] === 'boolean' }) &&
    ['dirtyPathCount', 'behindCount', 'lrnNext'].every(function(k) { return Number.isInteger(pf[k]) })
  if (!wellFormed) {
    if (pf && pf.error) log('Preflight error: ' + pf.error)
    return null
  }
  return pf
}

// Reads the wave file into groups, then cross-checks scope against the deterministic scan.
// Returns the wave, or { error } on any failure.
async function parseWave(pf, label) {
  const parsed = await callAgent(
    'Read the wave file at: ' + WAVE_FILE + '\n\n' +
    'Extract:\n' +
    '- waveId: the w[NNN] identifier from the filename.\n' +
    '- allCreates / allModifies: every in-repo FILE path the wave touches. Read the WHOLE of every\n' +
    '  Creates:/Modifies: line (bold **Creates:** / **Modifies:** headers and trailing "# ..." annotations\n' +
    '  included) and never stop at the first backticked path: paths may be backticked OR BARE,\n' +
    '  comma-separated, or inside prose. A "Creates:" line often names its real modify-set inside a\n' +
    '  parenthetical "(modifies `a`, `b`)" clause and its creates after "adds ...": a path inside a\n' +
    '  "modifies ..." clause goes to allModifies, every other path on a Creates: line to allCreates,\n' +
    '  every path on a Modifies: line to allModifies.\n' +
    '  A path names exactly one file whose final segment has a real extension (.py .js .ts .md .json\n' +
    '  .toml .yaml .yml .lock) or is a known dotfile/lockfile (uv.lock, .env.example, .gitignore, ...).\n' +
    '  Not paths: directories (ending "/"), globs ("*", "?"), slash-commands, identifiers or dotted\n' +
    '  attributes, bare extensions. A path with no "/" counts only for root-level files (.md .json\n' +
    '  .toml .yaml .yml .lock or a dotfile); write nested files with their full path.\n' +
    '  Skip todos marked [~] and paths in other repos. A wave with only Modifies: paths is valid.\n' +
    '- groups: execution groups. Todos sharing a ‖ group: label form one group; a todo without one\n' +
    '  gets label "ungrouped-N" (N = position). Each group carries its own creates and modifies\n' +
    '  (in-repo paths) and its todos (id, title, full body text).\n' +
    '- groupDeps: for each group label, the labels of OTHER groups named in its todos\' Depends:\n' +
    '  fields ([] when none; a dependency inside the same group adds nothing).\n\n' +
    'Return structured data.',
    { schema: WAVE_SCHEMA, label: label, phase: 'Parse' }
  )
  if (!parsed) {
    log('ERROR: could not parse wave file at ' + WAVE_FILE)
    return { error: 'parse-failed' }
  }
  const w = parsed
  // Unified review scope = Creates: ∪ Modifies:. Modify-only waves are legitimate.
  w.allCreates  = uniq(w.allCreates)
  w.allModifies = uniq(w.allModifies)
  w.allScope    = uniq(w.allCreates.concat(w.allModifies))
  // Deps and holds come from the todo scan of the wave file, not from the model's relay of it;
  // a todo the scan found that the model's groups lack means Parse dropped text.
  const modelIds = new Set()
  w.groups.forEach(function(g) { g.todos.forEach(function(t) { modelIds.add(t && t.id) }) })
  const unseen = pf.todoFacts.map(function(f) { return f.id }).filter(function(id) { return !modelIds.has(id) })
  if (unseen.length > 0) {
    log('ERROR: wave ' + w.waveId + ' Parse is missing ' + unseen.length + ' todo(s) the deterministic todo scan found: ' +
        unseen.join(', ') + ' — aborting rather than running with dropped Depends:/HUMAN GATE text. Re-run.')
    return { error: 'todo-scan-mismatch', waveId: w.waveId, missed: unseen }
  }
  w.todoFacts   = pf.todoFacts
  const heldIds = new Set(pf.todoFacts.filter(function(f) { return f.held }).map(function(f) { return f.id }))
  w.groupDeps   = deriveGroupDeps(w)
  for (const g of w.groups) {
    g.creates  = uniq(g.creates)
    g.modifies = uniq(g.modifies)
    g.scope    = uniq(g.creates.concat(g.modifies))
    g.held     = g.todos.some(function(t) { return heldIds.has(t && t.id) })
  }
  // The scan is the ground truth for which paths exist on Creates:/Modifies: lines; a path
  // the read missed would silently narrow every gate keyed off allScope.
  const scanned = uniq(pf.scopePaths)
  const missed = scanned.filter(function(p) { return w.allScope.indexOf(p) === -1 })
  if (missed.length > 0) {
    log('ERROR: wave ' + w.waveId + ' Parse missed ' + missed.length + ' path(s) the ' +
        'deterministic Creates:/Modifies: scan found: ' + missed.join(', ') +
        ' — aborting rather than running with a narrowed scope. Fix the wave file wording or re-run.')
    return { error: 'scope-scan-mismatch', waveId: w.waveId, missed: missed }
  }
  w.allScope = uniq(w.allScope.concat(scanned))
  if (w.allScope.length === 0) {
    log('ERROR: wave ' + w.waveId + ' has no Creates: AND no Modifies: paths — aborting ' +
        '(truly empty scope is a harness bug, not a clean wave)')
    return { error: 'empty-scope', waveId: w.waveId }
  }
  return w
}

// A wave that declares a template/ deliverable cannot land it unless the peer repo
// wailuen/a2a-agent-template is checked out at template/. Checked before any expensive phase.
function templateScopeUnlandable(w, pf) {
  const templatePaths = w.allScope.filter(function(p) { return p.startsWith('template/') })
  if (templatePaths.length === 0 || pf.templateDirExists) return false
  log('ABORT — wave ' + w.waveId + ' declares a template/ deliverable but template/ is not checked out in this working tree:')
  templatePaths.forEach(function(p) { log('  [template/ absent] ' + p) })
  log('Clone the peer repo (wailuen/a2a-agent-template) into template/ at the repo root, ' +
      'copy the declared file(s) in from their harness/workflows/ source, verify `diff` is empty, ' +
      'then `git -C template/ commit && git -C template/ push`. Re-run /wave ' + w.waveId +
      ' once template/ is checked out and the propagation can be verified.')
  return true
}

const preflight = await runPreflight('parse:preflight')
if (!preflight) {
  log('ERROR: preflight for ' + WAVE_FILE + ' returned no trustworthy result — aborting Parse')
  return { error: 'preflight-failed', waveFile: WAVE_FILE }
}

// This runner's protocol surfaces are src/-rooted; the a2a-sdk repo itself (agent_sdk/, no
// src/) would silently skip every protocol audit. sdk-wave.js is the runner there.
if (preflight.wrongRunnerForRepoLayout) {
  log('ABORT — this repo root has an agent_sdk/ package and no src/ directory: wave-cycle.js is ' +
      'the wrong runner here. Its protocol-surface arrays (AUTH_SURFACE, A2A_SURFACE, ' +
      'MCP_SURFACE, AGUI_SURFACE, A2UI_SURFACE) are hardcoded to src/-prefixed paths and can ' +
      'never match agent_sdk/ — every wave run this way silently skips the entire Protocol ' +
      'Audit phase. Use sdk-wave.js instead: .claude/skills/wave/SKILL.md launches it for this ' +
      'repo (Mode A step 2 and Mode B step 3).')
  return { error: 'wrong-runner-for-repo-layout' }
}

// Archive moves the wave file by basename; a reused ID would overwrite the earlier record.
if (preflight.completedFileExists) {
  log('ERROR: wave ID collision — workspace/todos/completed/' + WAVE_BASENAME + ' already ' +
      'exists. Archiving ' + WAVE_FILE + ' under this ID would overwrite the earlier wave\'s ' +
      'record. Rename this wave file (and any workspace/todos/deferred/' +
      WAVE_ID_FROM_FILE + '-*.md markers) to an unused wave ID, then re-run.')
  return { error: 'wave-id-collision', waveId: WAVE_ID_FROM_FILE, completedFile: 'workspace/todos/completed/' + WAVE_BASENAME }
}

// Two waves on one uncommitted tree produce a diff neither can be reviewed, reverted or
// released independently. An unknown dirty count (-1) counts as dirty.
if (preflight.otherActiveWaves && preflight.otherActiveWaves.length > 0 && preflight.dirtyPathCount !== 0) {
  log('ERROR: wave ' + WAVE_ID_FROM_FILE + ' cannot start — ' +
      preflight.otherActiveWaves.join(', ') + ' already sits in workspace/todos/active/ ' +
      'and the working tree has ' + (preflight.dirtyPathCount < 0 ? 'an unknown number of' : preflight.dirtyPathCount) +
      ' uncommitted path(s). Commit or archive the other wave first (or re-run this wave from a ' +
      'dedicated worktree).')
  return {
    error: 'concurrent-wave-uncommitted',
    waveId: WAVE_ID_FROM_FILE,
    otherActiveWaves: preflight.otherActiveWaves,
    dirtyPathCount: preflight.dirtyPathCount,
  }
}

// Work landed on a branch that has diverged from origin/main is not landed.
if (preflight.behindCount > 0) {
  log('ERROR: wave ' + WAVE_ID_FROM_FILE + ' cannot start — local main is ' +
      preflight.behindCount + ' commit(s) behind origin/main. Fetch and merge or rebase ' +
      'onto origin/main first, run the full suite + mypy on the merged tree, and ' +
      're-verify this wave\'s acceptance criteria against the post-merge code before ' +
      'Implement.')
  return { error: 'behind-origin', waveId: WAVE_ID_FROM_FILE, behindCount: preflight.behindCount }
}

let wave = await parseWave(preflight, 'parse')
if (wave.error) return wave
waveIdForBudgetNote = wave.waveId
if (templateScopeUnlandable(wave, preflight)) return { error: 'template-dir-missing', waveId: wave.waveId }

// Two concurrent wave runs would read the same lrnNext and overwrite each other's LRN
// files; waves run sequentially by design.
const lrnBase = preflight.lrnNext

function setBudgetFromWave() {
  AGENT_CALL_BUDGET = Number(normalizedArgs.agentBudget) || Math.max(150, 45 * wave.groups.length + 100)
}
setBudgetFromWave()
log('allScope (' + wave.allScope.length + '): ' + wave.allScope.join(', '))
log('Wave ' + wave.waveId + ': ' + wave.groups.length + ' group(s), ' +
    wave.allScope.length + ' scope path(s) (' + wave.allCreates.length + ' create / ' +
    wave.allModifies.length + ' modify), lrnNext=' + lrnBase + ', agent budget=' + AGENT_CALL_BUDGET)

// ─── phase 1: todos redteam ───────────────────────────────────────────────────
phase('Todos Redteam')

// Zero-tolerance plan review: every annotation, slice and propagation issue blocks. Rounds
// 1-3 are fixed by the planner (or a plain annotation write when that is all that is
// needed); from round 4 a fresh-lens debug pass replaces it. A null or self-contradicting
// review is unknown, never clean. After PLAN_MAX_ROUNDS without a clean review the wave stops
// before Implement.
function planIssueCount(r) {
  return r.reuseAnnotations.length + r.siAnnotations.length + r.sliceIssues.length + r.peerRepoAnnotations.length
}
function planIssuesOnly(r) {
  return {
    reuseAnnotations:    r.reuseAnnotations,
    siAnnotations:       r.siAnnotations,
    sliceIssues:         r.sliceIssues,
    peerRepoAnnotations: r.peerRepoAnnotations,
  }
}
function mergeCandidates(found) {
  for (const c of found || []) {
    const dup = registryCandidates.some(function(x) { return x.name === c.name && x.location === c.location })
    if (!dup) registryCandidates.push(c)
  }
}

const ANNOTATION_RULES =
  'Annotation format:\n' +
  '- Registry reuse: add `Reuses: <componentId>  # <note>` to the todo body.\n' +
  '- SI risk: add `SI: <siId>  # <note>` to the todo body.\n' +
  '- Peer-repo propagation: append the mirrorPath to the todo\'s Modifies: (or Creates:) line, with the\n' +
  '  note "lands via commit+push to wailuen/a2a-agent-template; implementer runs\n' +
  '  `git -C template/ commit && git -C template/ push` as an explicit final step".\n' +
  'Match each todo by its backticked ID on the checkbox line (e.g. `- [ ] `P1-01` ...`). Put new lines\n' +
  'right after the last indented field of that todo block. Preserve all other whitespace and structure.'

let planRound = 0
let planClean = false
let planEdited = false
let lastPlanIssues = null   // last trustworthy review with issues; null if every round was unknown
while (planRound < PLAN_MAX_ROUNDS) {
  planRound++
  const planRt = await callAgent(
    'Review the todo plan for wave ' + wave.waveId + ' before implementation starts.\n\n' +
    'Wave file: ' + WAVE_FILE + '\n' +
    'Also read workspace/components/README.md (C-NNN registry), workspace/learning/README.md\n' +
    '(Check/Prevention clauses) and .claude/reference/sdk-security-invariants.md (SI-1…SI-7).\n\n' +
    'Check these five things (cross-wave ordering is out of scope):\n' +
    '1. Registry reuse — a C-NNN component already covers a todo\'s capability and the todo has no\n' +
    '   `Reuses:` line for it → reuseAnnotations.\n' +
    '2. SI risk — a todo\'s Creates:/Modifies: paths touch SI-1…SI-7 territory and it has no `SI:` line\n' +
    '   for that invariant → siAnnotations.\n' +
    '3. Vertical slice — a todo is a horizontal layer rather than an end-to-end deliverable → sliceIssues.\n' +
    '4. New component candidates — planned code reusable across agents or waves → newCandidates\n' +
    '   (informational; not an issue).\n' +
    '5. Peer-repo propagation — a todo lists `.claude/workflows/<file>.js` or\n' +
    '   `harness/workflows/<file>.js` without `template/.claude/workflows/<file>.js`. The template copy\n' +
    '   is the third byte-identical mirror, in the peer repo wailuen/a2a-agent-template, and is never\n' +
    '   propagated implicitly → peerRepoAnnotations with that mirrorPath.\n\n' +
    'Report an annotation only when the wave file does not already carry it.\n' +
    'issuesFound is true when any of reuseAnnotations, siAnnotations, sliceIssues or\n' +
    'peerRepoAnnotations is non-empty, and false only when all four are empty.' +
    (lastPlanIssues
      ? '\n\nThis is round ' + planRound + '. The previous review reported the issues below and a fix was ' +
        'applied to the wave file. Confirm each is resolved and look for new ones:\n' +
        JSON.stringify(planIssuesOnly(lastPlanIssues), null, 2)
      : ''),
    { schema: PLAN_RT_SCHEMA, label: 'rt:todos:r' + planRound, phase: 'Todos Redteam', agentType: 'redteam' }
  )

  const wellFormed = planRt && ['reuseAnnotations', 'siAnnotations', 'sliceIssues', 'newCandidates', 'peerRepoAnnotations']
    .every(function(k) { return Array.isArray(planRt[k]) })
  if (!wellFormed) {
    log('WARNING: plan review returned no usable result at round ' + planRound + ' — unknown, not clean')
    continue
  }
  mergeCandidates(planRt.newCandidates)
  const issueCount = planIssueCount(planRt)
  if (issueCount === 0 && planRt.issuesFound) {
    log('WARNING: plan review at round ' + planRound + ' set issuesFound but listed no issues — unknown, not clean')
    continue
  }
  if (issueCount === 0) {
    planClean = true
    log('Todos plan clean at round ' + planRound +
        (registryCandidates.length > 0 ? ' (' + registryCandidates.length + ' new component candidate(s) flagged)' : ''))
    break
  }
  if (!planRt.issuesFound) log('WARNING: plan review listed ' + issueCount + ' issue(s) but issuesFound=false — treating them as issues')

  lastPlanIssues = planRt
  log('Todos plan round ' + planRound + ': ' + issueCount + ' issue(s) (reuse ' + planRt.reuseAnnotations.length +
      ', SI ' + planRt.siAnnotations.length + ', slice ' + planRt.sliceIssues.length +
      ', peer-repo ' + planRt.peerRepoAnnotations.length + ')')
  planRt.sliceIssues.forEach(function(s) { log('  [slice] ' + s.todoId + ': ' + s.issue) })
  if (planRound >= PLAN_MAX_ROUNDS) break

  const issuesJson = JSON.stringify(planIssuesOnly(planRt), null, 2)
  planEdited = true
  if (planRound > 3) {
    log('Plan review failed ' + planRound + ' consecutive rounds — fresh-lens debug pass on the plan')
    await callAgent(
      'The plan review for wave ' + wave.waveId + ' has failed ' + planRound + ' consecutive rounds.\n' +
      'Fresh-lens pass: read the wave file (' + WAVE_FILE + '), the PRD it implements (workspace/prd/) and\n' +
      'the issues below cold — do not trust earlier fix attempts. Find why the plan keeps failing review\n' +
      'and fix the wave file at the root so every issue below is resolved. Edit only the wave file.\n\n' +
      ANNOTATION_RULES + '\n\nIssues:\n' + issuesJson + '\n\nReport what you changed and why it failed before.',
      { label: 'debug:todos:r' + planRound, phase: 'Todos Redteam', agentType: 'debug' }
    )
  } else if (planRt.sliceIssues.length > 0) {
    await callAgent(
      'Fix the plan-review issues below in the wave file ' + WAVE_FILE + '.\n' +
      'Restructure each horizontal todo into a vertical slice, and add every annotation as listed. Keep todo\n' +
      'IDs, ‖ group labels and Depends: consistent, and keep each todo\'s Creates:/Modifies: lines accurate\n' +
      'for the files it will touch. Edit only the wave file.\n\n' +
      ANNOTATION_RULES + '\n\nIssues:\n' + issuesJson + '\n\nReport what you changed.',
      { label: 'plan:fix:r' + planRound, phase: 'Todos Redteam', agentType: 'planner' }
    )
  } else {
    await callAgent(
      'Annotate the wave file ' + WAVE_FILE + ' with the additions below.\n\n' +
      ANNOTATION_RULES + '\n\nAdditions:\n' + issuesJson + '\n\nReport which todos were annotated.',
      { label: 'plan:annotate:r' + planRound, phase: 'Todos Redteam', effort: 'low' }
    )
  }
}

if (!planClean) {
  log('BLOCKED — the todo plan for wave ' + wave.waveId + ' is not clean after ' + planRound + ' review round(s); stopping before Implement')
  await deferNote(
    wave.waveId + '-plan-review-blocked.md',
    'Include: wave ID (' + wave.waveId + '), wave file (' + WAVE_FILE + '), date (' + TODAY + '),\n' +
    'review rounds (' + planRound + '), and the open plan-review issues:\n' +
    (lastPlanIssues ? JSON.stringify(planIssuesOnly(lastPlanIssues), null, 2) : '(unknown — no review returned a usable result)') + '\n\n' +
    'Instruction in the file: "Resolve these plan issues in the wave file, then re-run /wave ' + wave.waveId + '".',
    'defer:todos:plan-review-blocked', 'Todos Redteam'
  )
  return {
    error: 'plan-review-blocked',
    waveId: wave.waveId,
    planReviewRounds: planRound,
    openIssues: lastPlanIssues ? planIssuesOnly(lastPlanIssues) : 'unknown',
  }
}

// Fixes changed the wave file: re-read it so implementers get the annotated todo bodies and
// every gate sees the final scope (e.g. an added template/ mirror path).
if (planEdited) {
  const pf2 = await runPreflight('parse:preflight:replan')
  if (!pf2) {
    log('ERROR: preflight after plan fixes returned no trustworthy result — aborting')
    return { error: 'preflight-failed', waveFile: WAVE_FILE }
  }
  const reparsed = await parseWave(pf2, 'parse:replan')
  if (reparsed.error) return reparsed
  wave = reparsed
  if (templateScopeUnlandable(wave, pf2)) return { error: 'template-dir-missing', waveId: wave.waveId }
  setBudgetFromWave()
  log('Wave re-read after plan fixes — ' + wave.groups.length + ' group(s), allScope (' + wave.allScope.length + '): ' + wave.allScope.join(', '))
}

// ─── phase 2: implement ───────────────────────────────────────────────────────
phase('Implement')

function implementPrompt(todo) {
  return 'Implement this todo. Read workspace/components/README.md first and reuse what it lists.\n\n' +
    'The security invariants SI-1…SI-7 in CLAUDE.md apply to everything you write.\n' +
    'Test-first for correctness-bearing code (tool logic, validation, serialisation): write the failing\n' +
    'test first and confirm RED, then the code and confirm GREEN, then refactor. The todo is not done\n' +
    'until its test was RED.\n\n' +
    'Todo:\n' + todo.body + '\n\n' +
    'Run only scoped tests (`' + PYTEST + ' tests/test_<specific>.py`) — a central gate runs the full\n' +
    'suite after all groups finish.\n' +
    'Report: files created/modified, RED→GREEN confirmation, any blockers.'
}

// A null implement result means the agent died: retry once, then block archive.
async function implementTodo(todo) {
  const opts = { label: 'impl:' + todo.id, phase: 'Implement', agentType: 'python-implementer' }
  let r = await callAgent(implementPrompt(todo), opts)
  if (!r) {
    log('WARNING: implement agent for ' + todo.id + ' returned null — retrying once')
    r = await callAgent(implementPrompt(todo), { label: 'impl:' + todo.id + ':retry', phase: 'Implement', agentType: 'python-implementer' })
  }
  if (!r) {
    log('ERROR: implement agent for ' + todo.id + ' returned null twice — archive will be blocked')
    implementBlocked = true
    protocolBlocked = true
  }
  return r
}

async function checkDeliverables(groups, since, label) {
  const spec = { since: since, groups: {} }
  groups.forEach(function(g) { spec.groups[g.label] = g.creates })
  const checkable = groups.filter(function(g) { return g.creates.length > 0 })
  const missing = {}
  if (checkable.length === 0) return missing
  const r = await callAgent(
    'Run this command at the repo root exactly as written (do not edit it) and return the JSON\n' +
    'object it prints, field for field. If it fails to run, set ok=false and put its error text in error.\n\n' +
    'python3 - ' + shq(JSON.stringify(spec)) + " <<'DELIVERABLE_GATE'\n" + DELIVERABLE_GATE_PY + '\nDELIVERABLE_GATE',
    { schema: DELIVERABLE_SCHEMA, label: label, phase: 'Implement', effort: 'low' }
  )
  const wellFormed = r && r.ok === true && Array.isArray(r.checked) && Array.isArray(r.missing) &&
    checkable.every(function(g) { return r.checked.indexOf(g.label) !== -1 }) &&
    r.missing.every(function(m) {
      return m && typeof m.label === 'string' && Array.isArray(m.paths) && groups.some(function(g) { return g.label === m.label })
    })
  if (!wellFormed) {
    log('WARNING: deliverable gate ' + label + ' returned no trustworthy result — every Creates: path counts as missing (fail closed)')
    checkable.forEach(function(g) { missing[g.label] = g.creates.slice() })
    return missing
  }
  r.missing.forEach(function(m) { if (m.paths.length > 0) missing[m.label] = m.paths })
  return missing
}

// Re-reads Creates:/Modifies: from the wave file at the top of every redteam round; paths added
// mid-run join the owning group's scope and wave.allScope (the archive gate's input). A null or
// malformed scan returns false: the caller treats the round as unknown, never clean.
async function rescanScope(base, round, group, phaseName) {
  const r = await callAgent(
    'Run this command at the repo root exactly as written (do not edit it). Set paths to the JSON\n' +
    'list it prints, unmodified.\n\n' +
    'python3 - ' + shq(WAVE_FILE) + " <<'SCOPE_SCAN'\n" + SCOPE_SCAN_PY + '\nSCOPE_SCAN',
    { schema: SCOPE_RESCAN_SCHEMA, label: 'scan:scope:' + base + ':r' + round, phase: phaseName, effort: 'low' }
  )
  if (!r || !Array.isArray(r.paths) || !r.paths.every(function(p) { return typeof p === 'string' })) return false
  const added = uniq(r.paths).filter(function(p) { return wave.allScope.indexOf(p) === -1 })
  added.forEach(function(p) {
    wave.allScope.push(p)
    const owners = wave.groups.filter(function(g) {
      return g.todos.some(function(t) { return String((t && t.body) || '').indexOf(p) !== -1 })
    })
    const targets = owners.length > 0 ? owners : (group ? [group] : [])
    targets.forEach(function(g) { if (g.scope.indexOf(p) === -1) g.scope.push(p) })
  })
  if (added.length > 0) log('Scope re-scan (' + base + ' r' + round + ') added ' + added.length + ' path(s): ' + added.join(', '))
  return true
}

// Tier-based execution: a tier is every group whose external deps are complete; groups in a
// tier run in parallel (the planner groups conflicting todos together).
const completedGroups = new Set()
const failedGroups = new Set()    // deliverables missing at the gate, or held at a HUMAN GATE
const heldGroups = new Set()
const prunedGroups = new Set()    // transitively depend on a failed group; never dispatched
const remainingGroups = wave.groups.slice()
const CLOCK_SCHEMA = {
  type: 'object',
  required: ['now'],
  additionalProperties: false,
  properties: { now: { type: 'number' } },
}

// The sandbox bans Date, so the Implement start time comes from a deterministic shell step.
// A null or malformed result returns null: the deliverable gate then counts every pattern
// path as missing (fail closed).
async function readImplementStart() {
  const r = await callAgent(
    'Run this command at the repo root exactly as written (do not edit it) and return the JSON\n' +
    'object it prints, field for field.\n\n' +
    'python3 -c ' + shq('import json,time;print(json.dumps({"now":time.time()}))'),
    { schema: CLOCK_SCHEMA, label: 'clock:implement-start', phase: 'Implement', effort: 'low' }
  )
  if (r && typeof r.now === 'number' && isFinite(r.now) && r.now > 1e9) return r.now
  log('WARNING: Implement start time unavailable — every pattern Creates: path counts as missing (fail closed)')
  return null
}

const implementStartSec = await readImplementStart()
let tierNo = 0

function pruneDependents() {
  const pruned = []
  let changed = true
  while (changed) {
    changed = false
    for (let i = remainingGroups.length - 1; i >= 0; i--) {
      const g = remainingGroups[i]
      const deps = (wave.groupDeps && wave.groupDeps[g.label]) || []
      if (deps.some(function(d) { return failedGroups.has(d) || prunedGroups.has(d) })) {
        remainingGroups.splice(i, 1)
        prunedGroups.add(g.label)
        pruned.push(g.label)
        changed = true
      }
    }
  }
  return pruned
}

while (remainingGroups.length > 0) {
  const heldNow = remainingGroups.filter(groupIsHeld)
  for (const hg of heldNow) {
    remainingGroups.splice(remainingGroups.indexOf(hg), 1)
    failedGroups.add(hg.label)
    heldGroups.add(hg.label)
    deliverablesBlocked = true
    protocolBlocked = true
    log('HUMAN GATE — group ' + hg.label + ' held: a todo carries the HUMAN GATE marker and no Release: line citing a GitHub issue URL')
    await deferNote(
      wave.waveId + '-group-' + hg.label + '-held.md',
      'Include: wave ID (' + wave.waveId + '), date (' + TODAY + '), group (' + hg.label + '),\n' +
      'reason: a todo in this group carries a HUMAN GATE marker with no `Release:` line citing a GitHub issue URL,\n' +
      'so the group was not dispatched and its dependents are pruned.\n' +
      'Instruction: "Record the approval in a GitHub issue, add `Release: <issue URL>` to the todo, ' +
      'then re-run /wave ' + wave.waveId + '."',
      'defer:held:' + hg.label, 'Implement'
    )
  }
  const prunedEarly = pruneDependents()
  if (prunedEarly.length > 0) {
    deliverablesBlocked = true
    protocolBlocked = true
    log('Pruned (depend on a held/failed group): ' + prunedEarly.join(', '))
  }
  if (remainingGroups.length === 0) break
  const readyGroups = remainingGroups.filter(function(g) {
    const deps = (wave.groupDeps && wave.groupDeps[g.label]) || []
    return deps.every(function(dep) { return completedGroups.has(dep) })
  })

  if (readyGroups.length === 0) {
    // Circular or unresolvable dep — record it, then run the first remaining group.
    const fallbackLabel = remainingGroups[0].label
    log('WARNING: unresolvable group dependency detected — circular dep chain likely. ' +
        'Writing deferred note and falling back to sequential for group ' + fallbackLabel)
    await deferNote(
      wave.waveId + '-circular-dep-' + fallbackLabel + '.md',
      'Include: wave ID (' + wave.waveId + '), date (' + TODAY + '), group (' + fallbackLabel + '),\n' +
      'reason: circular or unresolvable groupDeps — no group was ready to run.\n' +
      'Remaining groups: ' + remainingGroups.map(function(g) { return g.label }).join(', ') + '.\n' +
      'Instruction: "Inspect groupDeps in the wave file for cycles, fix them, ' +
      'then re-run /wave ' + wave.waveId + '."',
      'defer:circ-dep:' + fallbackLabel, 'Implement'
    )
    readyGroups.push(remainingGroups[0])
  }

  for (const rg of readyGroups) {
    const idx = remainingGroups.findIndex(function(g) { return g.label === rg.label })
    if (idx !== -1) remainingGroups.splice(idx, 1)
  }
  totalTodos += readyGroups.reduce(function(n, g) { return n + g.todos.length }, 0)
  if (readyGroups.length > 1) {
    log('Implementing ' + readyGroups.length + ' groups in parallel: ' + readyGroups.map(function(g) { return g.label }).join(', '))
  }

  await parallel(readyGroups.map(function(group) {
    return function() {
      log('Implementing group ' + group.label + ' (' + group.todos.length + ' todo(s))')
      return parallel(group.todos.map(function(todo) {
        return function() { return implementTodo(todo) }
      }))
    }
  }))
  if (agentCallCount > AGENT_CALL_BUDGET) {
    throw new Error('agent-call budget exceeded (' + AGENT_CALL_BUDGET + ' calls) for this wave')
  }
  tierNo++
  const missingByGroup = await checkDeliverables(readyGroups, implementStartSec, 'deliv:tier' + tierNo)
  const failedNow = readyGroups.filter(function(g) { return (missingByGroup[g.label] || []).length > 0 })
  for (const rg of readyGroups) {
    if (failedNow.indexOf(rg) === -1) completedGroups.add(rg.label)
    else failedGroups.add(rg.label)
  }
  if (failedNow.length > 0) {
    deliverablesBlocked = true
    protocolBlocked = true
    const prunedNow = pruneDependents()
    if (prunedNow.length > 0) log('Pruned (depend on an incomplete group): ' + prunedNow.join(', '))
    for (const fg of failedNow) {
      log('Group ' + fg.label + ' INCOMPLETE — missing deliverable(s): ' + missingByGroup[fg.label].join(', '))
      await deferNote(
        wave.waveId + '-group-' + fg.label + '-incomplete.md',
        'Include: wave ID (' + wave.waveId + '), date (' + TODAY + '), group (' + fg.label + '),\n' +
        'reason: the deliverable gate after Implement found these Creates: paths missing, unverified, or stale:\n' +
        missingByGroup[fg.label].join('\n') + '\n' +
        'Dependent groups pruned and not run: ' + (prunedNow.length > 0 ? prunedNow.join(', ') : 'none') + '.\n' +
        'Instruction: "Finish the missing deliverables, then re-run /wave ' + wave.waveId + '."',
        'defer:incomplete:' + fg.label, 'Implement'
      )
    }
  }
}

// Stale-finding filter: a finding must quote the exact current source line it is about. One
// deterministic script runs `grep -F` for each quote in its file; a quote that is gone means
// the finding is about code that no longer exists. Fail closed: an empty quote, a missing or
// unsafe path, a grep error, or an untrustworthy script result all KEEP the finding.
const STALE_CHECK_PY = [
  'import json, os, subprocess, sys',
  'items = json.loads(sys.argv[1])',
  'stale = []',
  'present = []',
  'for i, it in enumerate(items):',
  '    f, q = it.get("file") or "", it.get("quote") or ""',
  '    if not q.strip() or not f or os.path.isabs(f) or ".." in f.split("/") or not os.path.isfile(f):',
  '        continue',
  '    try:',
  '        rc = subprocess.run(["grep", "-F", "-q", "-e", q, "--", f], capture_output=True, timeout=30).returncode',
  '    except Exception:',
  '        continue',
  '    if rc == 1:',
  '        stale.append(i)',
  '    elif rc == 0:',
  '        present.append(i)',
  'print(json.dumps({"ok": True, "stale": stale, "present": present}))',
].join('\n')

const STALE_SCHEMA = {
  type: 'object',
  required: ['ok', 'stale'],
  additionalProperties: false,
  properties: {
    ok:      { type: 'boolean' },
    stale:   { type: 'array', items: { type: 'integer' } },
    present: { type: 'array', items: { type: 'integer' } },
  },
}

// Only a quote this loop has already seen present can go stale: a quote that was never in the
// file (invented, elided with "...", carrying a line-number prefix) is unverifiable, and the
// finding stays blocking. Round 1 therefore records presence and never drops.
// GH-223: every file+quote pair seen present by any stale check this wave. A candidate whose
// quote is gone now but was seen present earlier was fixed in-wave; a quote never seen present
// stays still-open.
const WAVE_VERIFIED_QUOTES = new Set()
const staleKey = function(f) { return String(f.file) + '\u0000' + String(f.quote) }

// Runs STALE_CHECK_PY over {file, quote} items; null unless the result is trustworthy.
async function runStaleScript(items, label, phaseName) {
  const r = await callAgent(
    'Run this command at the repo root exactly as written (do not edit it) and return the JSON\n' +
    'object it prints, field for field. If it fails to run, set ok=false and stale=[].\n\n' +
    'python3 -c ' + shq(STALE_CHECK_PY) + ' ' + shq(JSON.stringify(items)),
    { schema: STALE_SCHEMA, label: label, phase: phaseName, effort: 'low' }
  )
  const validIdx = function(i) { return Number.isInteger(i) && i >= 0 && i < items.length }
  const trusted = r && r.ok === true && Array.isArray(r.stale) && r.stale.every(validIdx) &&
    (r.present === undefined || (Array.isArray(r.present) && r.present.every(validIdx)))
  return trusted ? r : null
}

async function dropStaleFindings(findings, base, round, phaseName, verified) {
  const items = findings.map(function(f) { return { file: f && f.file, quote: f && f.quote } })
  if (!items.some(function(it) { return typeof it.quote === 'string' && it.quote.trim() !== '' })) return findings
  const r = await runStaleScript(items, 'stale:' + base + ':r' + round, phaseName)
  if (!r) {
    log('WARNING: stale-finding check for ' + base + ' returned no trustworthy result at round ' + round + ' — keeping every finding')
    return findings
  }
  const keyOf = staleKey
  const drop = new Set()
  for (const i of r.stale) {
    if (verified.has(keyOf(findings[i]))) {
      drop.add(i)
      log('stale finding dropped (quoted line no longer in ' + findings[i].file + '): ' + findings[i].id)
    } else {
      log('unverifiable quote kept (never found in ' + findings[i].file + '): ' + findings[i].id)
    }
  }
  ;(r.present || []).forEach(function(i) { verified.add(keyOf(findings[i])); WAVE_VERIFIED_QUOTES.add(keyOf(findings[i])) })
  return findings.filter(function(_f, i) { return !drop.has(i) })
}

// GH-223: opt-in auto-filing of still-open SDK candidates. The deterministic script below does the
// redaction, the dedupe search and the filing; no model writes a gh command. Title and body come
// only from classified fields (never quote or code), every gh call carries -R wailuen/a2a-sdk,
// and the body goes through --body-file.
const FILE_SDK_ISSUES_PY = [
  'import json, re, shutil, subprocess, sys, tempfile, os',
  'REPO = "wailuen/a2a-sdk"',
  'CAP = 10',
  'COMPONENTS = {"harness/skill", "harness/workflow", "harness/agent", "harness/template", "sdk/build", "sdk/loop", "sdk/credentials", "sdk/console", "protocol/a2a", "protocol/mcp", "protocol/ag-ui", "protocol/a2ui", "protocol/oauth", "security"}',
  'KEYLIKE = re.compile(r"\\b(?:sk|ak)[-_][A-Za-z0-9_-]+", re.I)',
  'TOKEN = re.compile(r"\\b(?:ghp|gho|ghu|ghs|github_pat|xox[abpr]|AKIA)[A-Za-z0-9_-]{8,}")',
  'XOX = re.compile(r"\\bxox[a-z]-[A-Za-z0-9-]+")',
  'GOOGLE = re.compile(r"\\bAIza[0-9A-Za-z_-]{35}")',
  'JWT = re.compile(r"\\beyJ[A-Za-z0-9_-]+(?:\\.[A-Za-z0-9_-]+)*")',
  'BASIC = re.compile(r"\\bBasic\\s+[A-Za-z0-9+/]{12,}={0,2}")',
  'GLPAT = re.compile(r"\\bglpat-[A-Za-z0-9_-]+")',
  'STRIPE = re.compile(r"\\b(?:pk|rk|sk)_(?:live|test)_[A-Za-z0-9]+")',
  'ASSIGN = re.compile(r"\\b(?:password|passwd|secret|token|api[_-]?key)\\s*[=:]\\s*\\S+", re.I)',
  'BEARER = re.compile(r"\\bbearer\\s+[A-Za-z0-9._~+/=-]+", re.I)',
  'HEX = re.compile(r"\\b[A-Fa-f0-9]{32,}\\b")',
  'LONG = re.compile(r"[A-Za-z0-9+/._-]{32,}={0,2}")',
  'PATS = (KEYLIKE, TOKEN, XOX, GOOGLE, JWT, BASIC, GLPAT, STRIPE, ASSIGN, BEARER, HEX)',
  'LOOSE = re.compile(r"\\b(?:sk|ak)[-_]", re.I)',
  'def mixed(m):',
  '    s = m.group(0)',
  '    return "[REDACTED]" if re.search(r"[a-z]", s) and re.search(r"[A-Z]", s) and re.search(r"[0-9]", s) else s',
  'def redact(s):',
  '    s = str(s or "")',
  '    for p in PATS:',
  '        s = p.sub("[REDACTED]", s)',
  '    return LONG.sub(mixed, s)',
  'def leaks(s):',
  '    return any(p.search(s) for p in PATS + (LOOSE,)) or LONG.sub(mixed, s) != s',
  'def ensure_label(name):',
  '    try:',
  '        return gh(["label", "create", name, "-R", REPO, "--force"]).returncode == 0',
  '    except Exception:',
  '        return False',
  'def norm(t):',
  '    return " ".join(str(t).lower().split())',
  'def gh(argv):',
  '    return subprocess.run(["gh"] + argv, capture_output=True, text=True, timeout=60)',
  'data = json.loads(sys.argv[1])',
  'out = {"ok": True, "ghAvailable": True, "results": []}',
  'prepared = []',
  'for c in data.get("candidates") or []:',
  '    desc = redact(c.get("description")).strip()',
  '    title = " ".join(desc.split())[:120]',
  '    fields = [desc, redact(c.get("component")), redact(c.get("severity")), redact(c.get("file"))]',
  '    if not title or any(leaks(f) for f in fields):',
  '        out["results"].append({"index": c.get("index"), "status": "skipped-secret"})',
  '    else:',
  '        prepared.append((c.get("index"), title, desc, fields[1], fields[2], fields[3]))',
  'if prepared and not shutil.which("gh"):',
  '    out["ghAvailable"] = False',
  '    prepared = []',
  'filed = 0',
  'for idx, title, desc, comp, sev, path in prepared:',
  '    if filed >= CAP:',
  '        out["results"].append({"index": idx, "status": "capped"})',
  '        continue',
  '    try:',
  '        r = gh(["issue", "list", "-R", REPO, "--state", "open", "--search", title, "--json", "number,title,url", "--limit", "20"])',
  '        if r.returncode != 0:',
  '            raise RuntimeError("list failed")',
  '        hits = [h for h in json.loads(r.stdout or "[]") if norm(h.get("title")) == norm(title)]',
  '    except Exception:',
  '        out["ghAvailable"] = False',
  '        break',
  '    if hits:',
  '        out["results"].append({"index": idx, "status": "duplicate", "url": hits[0].get("url", "")})',
  '        continue',
  '    body = "Auto-filed from wave %s.\\n\\nComponent: %s\\nSeverity: %s\\nFile: %s\\n\\n%s\\n" % (redact(data.get("waveId")), comp, sev, path or "n/a", desc)',
  '    fd, tmp = tempfile.mkstemp(suffix=".md")',
  '    try:',
  '        with os.fdopen(fd, "w") as fh:',
  '            fh.write(body)',
  '        argv = ["issue", "create", "-R", REPO, "--title", title, "--body-file", tmp]',
  '        if ensure_label("auto-filed"):',
  '            argv += ["--label", "auto-filed"]',
  '        if comp in COMPONENTS and ensure_label(comp):',
  '            argv += ["--label", comp]',
  '        r = gh(argv)',
  '        if r.returncode != 0 and "--label" in argv:',
  '            r = gh(["issue", "create", "-R", REPO, "--title", title, "--body-file", tmp])',
  '    except Exception:',
  '        r = None',
  '    finally:',
  '        if os.path.exists(tmp):',
  '            os.remove(tmp)',
  '    if r is None or r.returncode != 0:',
  '        out["results"].append({"index": idx, "status": "failed"})',
  '        continue',
  '    filed += 1',
  '    lines = (r.stdout or "").strip().splitlines()',
  '    out["results"].append({"index": idx, "status": "filed", "url": lines[-1] if lines else ""})',
  'print(json.dumps(out))'
].join('\n')
const FILE_SCHEMA = {
  type: 'object',
  required: ['ok', 'ghAvailable', 'results'],
  additionalProperties: false,
  properties: {
    ok:          { type: 'boolean' },
    ghAvailable: { type: 'boolean' },
    results: {
      type: 'array',
      items: {
        type: 'object',
        required: ['index', 'status'],
        additionalProperties: false,
        properties: {
          index:  { type: 'integer' },
          status: { type: 'string' },
          url:    { type: 'string' },
        },
      },
    },
  },
}

const AUTO_FILE_SDK_ISSUES = normalizedArgs.autoFileSdkIssues === true || normalizedArgs.autoFileSdkIssues === 'true'

function originalFinding(c) {
  const hits = toCodeify.filter(function(f) { return f.id === c.id && f.file === c.file && f.quote === c.quote })
  return hits.length === 1 ? hits[0] : null
}

// fixed-in-wave only when the quote is gone now AND was seen present earlier in this wave;
// every other outcome (empty quote, never verified, bad path, untrusted result) is still-open.
async function candidateStatuses(candidates) {
  const statuses = candidates.map(function() { return 'still-open' })
  const subjects = candidates.map(originalFinding)
  const items = subjects.map(function(s, i) { return s ? { file: s.file, quote: s.quote } : { file: candidates[i].file, quote: '' } })
  if (!items.some(function(it) { return typeof it.quote === 'string' && it.quote.trim() !== '' })) return statuses
  const r = await runStaleScript(items, 'sdk:recheck', 'Codify')
  if (!r) {
    log('WARNING: SDK candidate re-check returned no trustworthy result — every candidate stays still-open')
    return statuses
  }
  for (const i of r.stale) {
    if (subjects[i] && WAVE_VERIFIED_QUOTES.has(staleKey(subjects[i]))) statuses[i] = 'fixed-in-wave'
  }
  return statuses
}

async function fileStillOpenCandidates(candidates, statuses) {
  const urls = {}
  const open = []
  candidates.forEach(function(c, i) {
    if (statuses[i] === 'still-open') {
      open.push({ index: i, description: c.description, component: c.component, severity: c.severity, file: c.file || '' })
    }
  })
  if (open.length === 0) { log('autoFileSdkIssues: no still-open candidates to file'); return urls }
  const r = await callAgent(
    'Run this command at the repo root exactly as written (do not edit it) and return the JSON\n' +
    'object it prints, field for field. If it fails to run, set ok=false, ghAvailable=false, results=[].\n\n' +
    'python3 -c ' + shq(FILE_SDK_ISSUES_PY) + ' ' + shq(JSON.stringify({ waveId: wave.waveId, candidates: open })),
    { schema: FILE_SCHEMA, label: 'sdk:file', phase: 'Codify', effort: 'low' }
  )
  if (!r || r.ok !== true || !Array.isArray(r.results)) {
    log('WARNING: autoFileSdkIssues returned no trustworthy result — candidates stay in workspace/sdk-candidates.md for /sdk-issue-scan')
    return urls
  }
  if (r.ghAvailable === false) log('WARNING: gh is unavailable or unauthenticated — candidates stay in workspace/sdk-candidates.md for /sdk-issue-scan')
  r.results.forEach(function(x) {
    if (x.url && (x.status === 'filed' || x.status === 'duplicate')) urls[x.index] = x.status + ': ' + x.url
    if (x.status === 'skipped-secret') log('autoFileSdkIssues: candidate ' + (x.index + 1) + ' still matches a secret pattern after redaction — left for manual /sdk-issue-scan')
  })
  return urls
}

// ─── redteam fix loop (shared by unit and phase) ──────────────────────────────
// One loop for both levels so they cannot drift apart:
//   review → null or findingsCount/findings mismatch = unknown (round counts, stall memory kept)
//          → no critical/high = clean
//          → round budget reached = deferred note + 'budget' (findings survived)
//          → fix: debug replaces the fix fan-out at round 4+ or when findings repeat
//          → gate (+ one test fix + re-gate); null or still red = 'tests'
// Outcomes: 'clean' | 'budget' | 'unknown' | 'tests'.
async function redteamFixLoop(cfg) {
  let round = 0
  let prevSigs = new Set()
  const nonBlockingStore = []
  const nonBlockingSigs = new Set()
  let outcome = 'clean'
  const verifiedQuotes = new Set()   // file+quote pairs seen present in an earlier or current round

  while (true) {
    round++
    const scanOk = cfg.rescan ? await cfg.rescan(round) : true
    const rt = scanOk ? await callAgent(cfg.reviewPrompt(),
      { schema: RT_SCHEMA, label: 'rt:' + cfg.base + ':r' + round, phase: cfg.phase, agentType: 'redteam' }) : null

    const unknown = !scanOk ? 'skipped: Creates:/Modifies: scope re-scan returned no trustworthy result'
      : !rt ? 'returned null'
      : (!Array.isArray(rt.findings) || rt.findingsCount !== rt.findings.length)
        ? 'reported findingsCount=' + rt.findingsCount + ' but findings array has ' + (Array.isArray(rt.findings) ? rt.findings.length : 'no') + ' item(s)'
        : null
    if (unknown) {
      log('WARNING: ' + cfg.base + ' redteam ' + unknown + ' at round ' + round + ' — treating as unknown (not clean)')
      if (round >= cfg.maxRounds) {
        await deferNote(
          cfg.stem + (!rt ? '-rt-null-budget.md' : '-rt-mismatch-budget.md'),
          'Include: wave ID (' + wave.waveId + '), scope (' + cfg.base + '), date (' + TODAY + '),\n' +
          'round (' + round + '), reason: redteam ' + unknown + ' on every round — unknown state.\n' +
          'Instruction: "Re-run /wave ' + wave.waveId + ' to retry this redteam."',
          'defer:' + cfg.base + (!rt ? ':rt-null-budget' : ':rt-mismatch-budget'), cfg.phase
        )
        outcome = 'unknown'
        break
      }
      continue
    }

    rt.findings = await dropStaleFindings(rt.findings, cfg.base, round, cfg.phase, verifiedQuotes)

    const blocking = blockingFindings(rt.findings)
    const nonBlocking = nonBlockingFindings(rt.findings)
    accumulateNonBlocking(nonBlockingStore, nonBlockingSigs, rt.findings)

    if (blocking.length === 0) {
      log(cfg.base + ' clean at round ' + round + ' (no critical/high findings)' +
          (nonBlocking.length > 0 ? '; ' + nonBlocking.length + ' medium/low finding(s) deferred' : ''))
      break
    }
    log(cfg.base + ' round ' + round + ': ' + blocking.length + ' blocking finding(s)' +
        (nonBlocking.length > 0 ? ' (+' + nonBlocking.length + ' medium/low, non-blocking)' : ''))

    const curSigs = sigs(blocking)
    const stalled = round > 1 && sigsEqual(curSigs, prevSigs)

    // Surviving critical/high findings reach Codify on every exit path, including the cap.
    const missingCodify = blocking.filter(function(f) { return !f.codify })
    if (missingCodify.length > 0) {
      log('WARNING: ' + missingCodify.length + ' critical/high finding(s) in ' + cfg.base +
          ' missing a Codify: line: ' + missingCodify.map(function(f) { return f.id }).join(', '))
    }
    allHighFindings.push.apply(allHighFindings, blocking)

    if (round >= cfg.maxRounds) {
      log('Round budget exhausted for ' + cfg.base + ' — deferring and blocking archive (surviving critical/high findings)')
      await deferNote(
        cfg.stem + '-budget-exhausted.md',
        'Include: wave ID (' + wave.waveId + '), scope (' + cfg.base + '), date (' + TODAY + '),\n' +
        'round count (' + round + '), and the final findings:\n' +
        JSON.stringify(rt.findings, null, 2) + '\n\n' +
        'Instruction in the file: "Fix remaining findings, then re-run /wave ' + wave.waveId + '".',
        'defer:' + cfg.base + ':budget-exhausted', cfg.phase
      )
      outcome = 'budget'
      break
    }

    const gateResult = await cfg.withLock(async function() {
      const escalateToDebug = round > 3 || stalled
      if (escalateToDebug) {
        log((stalled ? 'Stall detected — ' : 'Round 4+ — ') + 'escalating to debug agent (replaces fix fan-out this round)')
        await callAgent(
          'Fix loop for ' + cfg.base + ' needs a fresh-lens analysis' +
          (stalled ? ' (stalled: same findings across 2 rounds)' : ' (round ' + round + ')') + '.\n\n' +
          'Findings:\n' + JSON.stringify(blocking, null, 2) + '\n\n' +
          'Scope:\n' + cfg.scope.join('\n') + '\n\n' +
          'Read the code cold, diagnose the root cause, and fix it at the root.',
          { label: 'debug:' + cfg.base + ':r' + round, phase: cfg.phase, agentType: 'debug' }
        )
      } else {
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
                  'Fix these findings in ' + file + ':\n\n' + JSON.stringify(byFile[file], null, 2) + '\n\n' +
                  'Keep SI-1…SI-7 intact. Run `' + PYTEST + '` on the affected tests after.',
                  { label: 'fix:' + cfg.base + ':r' + round + ':' + file.replace(/\//g, '-'),
                    phase: cfg.phase, agentType: 'python-implementer' }
                )
              }
            })
          : [function() {
              return callAgent(
                'Fix these findings, grouped by file:\n\n' + JSON.stringify(byFile, null, 2) + '\n\n' +
                'Keep SI-1…SI-7 intact. Run `' + PYTEST + '` on the affected tests after.',
                { label: 'fix:' + cfg.base + ':r' + round, phase: cfg.phase, agentType: 'python-implementer' }
              )
            }]
        await parallel(fixTasks)
      }
      prevSigs = curSigs
      return gateWithTestFix(cfg.base + ':r' + round, cfg.phase)
    })

    if (gateResult !== 'green') {
      await deferNote(
        cfg.stem + (gateResult === 'null' ? '-gate-null-r' : '-tests-red-r') + round + '.md',
        'Include: wave ID (' + wave.waveId + '), scope (' + cfg.base + '), date (' + TODAY + '),\n' +
        'round (' + round + '), reason: ' + (gateResult === 'null'
          ? 'test gate returned null (unknown test state)'
          : 'test suite RED after the fix attempt') + ', with these blocking findings unresolved:\n' +
        JSON.stringify(blocking, null, 2) + '\n\n' +
        'Instruction: "Fix failing tests and remaining findings, then re-run /wave ' + wave.waveId + '".',
        'defer:' + cfg.base + (gateResult === 'null' ? ':gate-null:r' : ':tests-red:r') + round, cfg.phase
      )
      outcome = 'tests'
      break
    }
  }

  if (nonBlockingStore.length > 0) {
    await deferNote(
      cfg.stem + '-medium-low.md',
      'Include: wave ID (' + wave.waveId + '), scope (' + cfg.base + '), date (' + TODAY + '),\n' +
      'non-blocking (medium/low) findings accumulated across every redteam round (deduped by file+description):\n' +
      JSON.stringify(nonBlockingStore, null, 2) + '\n\n' +
      'Instruction in the file: "Non-blocking — these did not block ' + wave.waveId + '\'s archive. ' +
      'Address opportunistically or fold into a future wave."',
      'defer:' + cfg.base + ':medium-low', cfg.phase
    )
  }
  return { rounds: round, outcome: outcome }
}

function applyLoopOutcome(outcome, budgetFlag) {
  if (outcome === 'clean') return
  protocolBlocked = true
  if (outcome === 'budget') {
    if (budgetFlag === 'unit') unitBudgetBlocked = true
    else phaseBudgetBlocked = true
  } else if (outcome === 'unknown') {
    redteamUnknownBlocked = true
  } else if (outcome === 'tests') {
    fixLoopTestsBlocked = true
  }
}

// ─── phase 3: unit redteam (per group, zero-tolerance) ───────────────────────
phase('Unit Redteam')

// Held and pruned groups never ran; reviewing absent files only produces noise.
const unitGroups = wave.groups.filter(function(g) { return !heldGroups.has(g.label) && !prunedGroups.has(g.label) })

// Groups have disjoint scope, so their loops run concurrently. The pytest gate reads the
// whole repo, so each round's mutate-and-verify section (fix → gate → re-gate) is serialised
// across groups; reviews stay outside the lock.
let gateLock = Promise.resolve()
function withGateLock(fn) {
  const run = gateLock.then(fn, fn)
  gateLock = run.then(function() {}, function() {})
  return run
}
function noLock(fn) { return fn() }

// Two scope paths collide when equal or when one is a directory prefix of the other. If
// any groups collide, the planner invariant does not hold: run groups one at a time.
function scopePathsOverlap(a, b) {
  if (a === b) return true
  const aDir = a.charAt(a.length - 1) === '/' ? a : a + '/'
  const bDir = b.charAt(b.length - 1) === '/' ? b : b + '/'
  return b.indexOf(aDir) === 0 || a.indexOf(bDir) === 0
}
const scopeOverlaps = []
unitGroups.forEach(function(a, ai) {
  unitGroups.slice(ai + 1).forEach(function(b) {
    const shared = a.scope.filter(function(p) {
      return b.scope.some(function(q) { return scopePathsOverlap(p, q) })
    })
    if (shared.length > 0) scopeOverlaps.push({ a: a.label, b: b.label, shared: shared })
  })
})

async function runUnitRedteamForGroup(group) {
  log('Unit redteam — group ' + group.label)
  const res = await redteamFixLoop({
    base: 'unit:' + group.label,
    stem: wave.waveId + '-group-' + group.label,
    phase: 'Unit Redteam',
    maxRounds: UNIT_MAX_ROUNDS,
    scope: group.scope,
    withLock: withGateLock,
    reviewPrompt: function() { return (
      'Adversarial review of the files created/modified by group ' + group.label + '.\n\n' +
      'Scope (Creates: AND Modifies: paths for this group):\n' + group.scope.join('\n') + '\n\n' +
      'Also check their transitive callers and importers.\n\n' +
      'Run all 8 dimensions from agents/core/redteam.md. Include the SDK Security\n' +
      'Invariants (SI-1…SI-7) in the security dimension — fail closed.\n\n' +
      'Return structured findings.') },
    rescan: function(r) { return rescanScope('unit:' + group.label, r, group, 'Unit Redteam') },
  })
  applyLoopOutcome(res.outcome, 'unit')
  return { label: group.label, rounds: res.rounds }
}

if (scopeOverlaps.length > 0) {
  scopeOverlaps.forEach(function(o) {
    log('WARNING: groups ' + o.a + ' and ' + o.b + ' share scope path(s): ' + o.shared.join(', '))
  })
  log('Scope overlap detected — planner disjointness invariant violated; running Unit Redteam ' +
      'one group at a time for this wave (concurrent path skipped)')
  for (const group of unitGroups) {
    await runUnitRedteamForGroup(group)
  }
} else {
  if (unitGroups.length > 1) {
    log('Unit redteam — ' + unitGroups.length + ' groups concurrently (fix + gate serialised): ' +
        unitGroups.map(function(g) { return g.label }).join(', '))
  }
  const unitResults = await parallel(unitGroups.map(function(group) {
    return function() { return runUnitRedteamForGroup(group) }
  }))
  // parallel() maps a thrown thunk to null: re-raise a budget throw, and treat any other
  // aborted group as unknown — it never established a verdict.
  if (agentCallCount > AGENT_CALL_BUDGET) {
    throw new Error('agent-call budget exceeded (' + AGENT_CALL_BUDGET + ' calls) for this wave')
  }
  unitResults.forEach(function(r, i) {
    if (!r) {
      log('WARNING: unit redteam for group ' + unitGroups[i].label + ' aborted with an error before a clean exit — not clean; re-run /wave ' + wave.waveId)
      protocolBlocked = true
      redteamUnknownBlocked = true
    }
  })
}

// ─── phase 4: phase redteam (whole wave, zero-tolerance) ─────────────────────
phase('Phase Redteam')

// On a single-group wave the union scope IS the group's scope, which Unit Redteam just
// cleared with the same machinery; only multi-group waves have a cross-group surface.
let pRound = 0
if (wave.groups.length === 1) {
  log('Phase Redteam skipped — single-group wave (' + wave.groups[0].label + '): Unit Redteam already reviewed this exact scope ' +
      'with the same review dimensions; no cross-group interaction surface exists.')
} else {
  const res = await redteamFixLoop({
    base: 'phase',
    stem: wave.waveId + '-phase',
    phase: 'Phase Redteam',
    maxRounds: PHASE_MAX_ROUNDS,
    scope: wave.allScope,
    withLock: noLock,
    reviewPrompt: function() { return (
      'Adversarial review of the full wave ' + wave.waveId + '.\n\n' +
      'Scope (all Creates: AND Modifies: paths across every group):\n' +
      wave.allScope.join('\n') + '\n\n' +
      'Also check transitive callers and importers, and the interactions between groups.\n\n' +
      'Run all 8 dimensions. SDK Security Invariants (SI-1…SI-7) fail closed.\n\n' +
      'Return structured findings.') },
    rescan: function(r) { return rescanScope('phase', r, null, 'Phase Redteam') },
  })
  pRound = res.rounds
  applyLoopOutcome(res.outcome, 'phase')
}

// ─── phase 5: protocol audit ──────────────────────────────────────────────────
phase('Protocol Audit')

function inSurface(surface) {
  return function(p) { return surface.some(function(pp) { return p.indexOf(pp) !== -1 }) }
}
// Full scope (Creates: ∪ Modifies:): a modify-only wave that edits a route still gets audited.
const PROTOCOLS = [
  { key: 'a2a',  name: 'A2A',   agentType: 'a2a-advisor',   surface: A2A_SURFACE,
    title: 'A2A v0.3.0 conformance audit.',
    check: 'Check: agent card shape, task/message/part/artifact shapes, streaming,\n' +
           'error codes (-32001 through -32007 → correct HTTP status), auth.' },
  { key: 'mcp',  name: 'MCP',   agentType: 'mcp-advisor',   surface: MCP_SURFACE,
    title: 'MCP conformance audit.',
    check: 'Check: Streamable-HTTP transport, OAuth 2.1 discovery (/.well-known/oauth-authorization-server),\n' +
           'PKCE (S256, code_challenge_method), initialize request/response echo (protocolVersion,\n' +
           'serverInfo, capabilities), tools/list shape (name, description, inputSchema),\n' +
           'token endpoint CORS, and auth error codes.' },
  { key: 'agui', name: 'AG-UI', agentType: 'ag-ui-advisor', surface: AGUI_SURFACE,
    title: 'AG-UI conformance audit.',
    check: 'Check: SSE event catalog (34 types), RunAgentInput schema, camelCase wire,\n' +
           'RUN_STARTED first / RUN_FINISHED last, CUSTOM event spec, bare data: frames.' },
  // Content-type counts must match DESIGN.md §5.4 and agent_sdk/models/content_types.py.
  { key: 'a2ui', name: 'A2UI',  agentType: 'a2ui-advisor',  surface: A2UI_SURFACE,
    title: 'A2UI v0.9.1 + Standard Profile v1.1 conformance audit.',
    check: 'Check: createSurface/updateComponents/updateDataModel/deleteSurface shapes,\n' +
           'Core 6 + Extended 8 Standard Profile types only (14 FROZEN total; 4 RESERVED: TradeActivity, CompanyInfo, DealList, InvestorProfile — never emitted), JSON-Pointer binding,\n' +
           'A2A DataPart delivery, translator.py message types, field contracts.' },
].filter(function(p) { return wave.allScope.some(inSurface(p.surface)) })

if (PROTOCOLS.length === 0) {
  log('Protocol audit skipped — no protocol surfaces in scope (Creates: ∪ Modifies:)')
} else {
  log('Protocol audit triggered (' + PROTOCOLS.map(function(p) { return p.name }).join(', ') + ')')
  log('Protocol audit: requires a2a-advisor / mcp-advisor / ag-ui-advisor / a2ui-advisor from the check kit. ' +
      'If the kit is absent, advisor legs return partial or empty results — NOT a green pass.')

  // Seam markers match WHOLE path segments (a basename minus extension, or a directory), so
  // 'mcptools' is not 'mcp'. They only narrow the hint line; the seam leg always runs, with
  // the full scope, whenever any protocol surface is in scope.
  const SEAM_ROUTE_MARKERS = ['routes', 'a2a', 'mcp', 'agent_card', 'ag_ui', 'a2ui']
  const seamPaths = wave.allScope.filter(function(p) {
    return p.split('/').some(function(seg) {
      return SEAM_ROUTE_MARKERS.indexOf(seg.replace(/\.[^./]+$/, '')) !== -1
    })
  })
  const seamHint = seamPaths.length > 0 ? seamPaths.join('\n') : '(none matched by name — shared/auth surface change; see full scope below)'

  // A null advisor is a dropped verdict: unknown, never clean.
  const runAdvisors = async function(tasks, what) {
    const raw = await parallel(tasks)
    const nulls = raw.filter(function(r) { return !r }).length
    if (nulls > 0) {
      log('WARNING: ' + nulls + ' protocol ' + what + ' advisor(s) returned null — treating as unknown (not clean); archive BLOCKED')
      protocolBlocked = true
    }
    return raw.filter(Boolean)
  }

  const protoResults = await runAdvisors(PROTOCOLS.map(function(p) {
    return function() {
      return callAgent(
        p.title + '\n\nFiles to audit:\n' + wave.allScope.filter(inSurface(p.surface)).join('\n') + '\n\n' +
        p.check + '\n\nReturn structured findings. Set protocol="' + p.name + '" per finding.',
        { schema: PROTO_SCHEMA, agentType: p.agentType, label: 'proto:' + p.key, phase: 'Protocol Audit' }
      )
    }
  }).concat([function() {
    // No specialist owns the seam: it reads several protocol surfaces together.
    return callAgent(
      'Cross-protocol seam audit — consistency ACROSS A2A, MCP, AG-UI, A2UI surfaces.\n\n' +
      'Candidate route/shared surfaces in scope (derived from wave scope):\n' + seamHint + '\n\n' +
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
  }]), 'audit')

  let protoCritical = protoResults.reduce(function(n, r) { return n + (r.criticalCount || 0) }, 0)
  const protoHigh   = protoResults.reduce(function(n, r) { return n + (r.highCount || 0) }, 0)
  const allProtoFindings = protoResults.reduce(function(acc, r) { return acc.concat(r.findings || []) }, [])
  log('Protocol audit: ' + protoCritical + ' critical, ' + protoHigh + ' high')

  const protoBlocking = allProtoFindings.filter(function(f) {
    return f.severity === 'critical' || f.severity === 'high'
  })
  const missingCodifyProto = protoBlocking.filter(function(f) { return !f.codify })
  if (missingCodifyProto.length > 0) {
    log('WARNING: ' + missingCodifyProto.length + ' critical/high protocol finding(s) missing a ' +
        'Codify: line: ' + missingCodifyProto.map(function(f) { return f.protocol + ':' + f.rule }).join(', '))
  }
  allHighFindings.push.apply(allHighFindings, protoBlocking.map(function(f) {
    return {
      id:          'proto-' + f.protocol + '-' + f.rule.replace(/[^a-z0-9]/gi, '-').toLowerCase(),
      severity:    f.severity,
      file:        'protocol-surface',
      description: f.description,
      fix:         f.fix || ('See protocol-audit findings for ' + f.protocol + ' rule ' + f.rule),
      codify:      f.codify,
    }
  }))

  if (protoCritical > 0) {
    log('Critical protocol findings — dispatching fix agent')
    await callAgent(
      'Fix ALL critical protocol conformance findings below. These block archive.\n\n' +
      'Findings:\n' + JSON.stringify(allProtoFindings.filter(function(f) { return f.severity === 'critical' }), null, 2) + '\n\n' +
      'Run `' + PYTEST + '` after fixing. Report files changed.',
      { label: 'proto:fix', phase: 'Protocol Audit', agentType: 'python-implementer' }
    )

    const protoGate = await gateWithTestFix('proto:fix', 'Protocol Audit', 'introduced by the protocol fix')
    if (protoGate !== 'green') {
      log('Proto gate ' + (protoGate === 'null' ? 'returned null' : 'still RED after test-fix') + ' — skipping recheck; archive will be blocked')
      fixLoopTestsBlocked = true
      protocolBlocked = true
      await deferNote(
        wave.waveId + '-proto-tests-red.md',
        'Include: wave ID (' + wave.waveId + '), date (' + TODAY + '),\n' +
        'reason: test suite ' + (protoGate === 'null' ? 'state unknown (gate returned null)' : 'RED') + ' after the protocol fix.\n' +
        'Instruction: "Fix failing tests and re-run /wave ' + wave.waveId + '".',
        'defer:proto:tests-red', 'Protocol Audit'
      )
    } else {
      const recheck = await runAdvisors(PROTOCOLS.map(function(p) {
        return function() {
          return callAgent(
            p.name + ' re-audit after the preceding fix. Check the same surfaces.\n' +
            'Scope paths (Creates: ∪ Modifies:):\n' + wave.allScope.join('\n') + '\n' +
            'Focus on the previously-critical findings. Return structured findings. Set protocol="' + p.name + '" per finding.',
            { schema: PROTO_SCHEMA, agentType: p.agentType, label: 'proto:recheck:' + p.key, phase: 'Protocol Audit' }
          )
        }
      }).concat([function() {
        return callAgent(
          'Cross-protocol seam re-audit after the preceding fix.\n' +
          'Candidate route/shared surfaces in scope:\n' + seamHint + '\n' +
          'Scope paths (Creates: ∪ Modifies:):\n' + wave.allScope.join('\n') + '\n' +
          'Focus on the previously-critical SEAM findings. Return structured findings. Set protocol="SEAM" per finding.',
          { schema: PROTO_SCHEMA, label: 'proto:recheck:seam', phase: 'Protocol Audit' }
        )
      }]), 'recheck')
      protoCritical = recheck.reduce(function(n, r) { return n + (r.criticalCount || 0) }, 0)
      if (protoCritical > 0) {
        log('BLOCKED — critical protocol findings persist; wave will not archive')
        protocolBlocked = true
        await deferNote(
          wave.waveId + '-protocol-blocked.md',
          'Include: wave ID (' + wave.waveId + '), date (' + TODAY + '), the unresolved critical\n' +
          'findings from the recheck:\n' + JSON.stringify(recheck.reduce(function(acc, r) {
            return acc.concat((r.findings || []).filter(function(f) { return f.severity === 'critical' }))
          }, []), null, 2) + '\n\nand the instruction:\n' +
          '"Fix protocol findings, then run /agent-verify, then re-run /wave ' + wave.waveId + '".',
          'proto:defer-note', 'Protocol Audit'
        )
      }
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

// Only individual LRN capture is capped; the SDK issue scan still sees every finding.
const lrnCandidates = toCodeify.slice(0, MAX_LRN_PER_WAVE)
if (toCodeify.length > MAX_LRN_PER_WAVE) {
  const overflowLrnCandidates = toCodeify.slice(MAX_LRN_PER_WAVE)
  log('WARNING: ' + toCodeify.length + ' critical/high finding(s) — capping LRN capture at ' +
      MAX_LRN_PER_WAVE + ' per wave (' + overflowLrnCandidates.length +
      ' finding(s) already fixed but not individually codified)')
  await deferNote(
    wave.waveId + '-lrn-cap-exceeded.md',
    'Include: wave ID (' + wave.waveId + '), date (' + TODAY + '), MAX_LRN_PER_WAVE (' +
    MAX_LRN_PER_WAVE + '), and the ' + overflowLrnCandidates.length + ' finding(s) that exceeded ' +
    'the per-wave LRN capture cap (already fixed by the redteam loop, but not individually ' +
    'codified as LRN files):\n' +
    JSON.stringify(overflowLrnCandidates, null, 2) + '\n\n' +
    'Instruction in the file: "These findings were already fixed but not codified as LRN files ' +
    'due to the ' + MAX_LRN_PER_WAVE + '-per-wave cap. Review and codify opportunistically, or ' +
    'fold into a future wave."',
    'defer:codify:lrn-cap-exceeded', 'Codify'
  )
}

log('Codifying ' + lrnCandidates.length + ' critical/high finding(s)' +
    (toCodeify.length > MAX_LRN_PER_WAVE ? ' (of ' + toCodeify.length + ' total)' : ''))

// SDK-level findings go to workspace/sdk-candidates.md for /sdk-issue-scan.
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
    'Copy each candidate\'s finding id and quote UNCHANGED from the finding (you may rewrite the\n' +
    'description, never id or quote).\n\n' +
    'If this repo is the a2a-sdk repo itself (it has an agent_sdk/ package), EXCLUDE findings\n' +
    'about the wave\'s own process: CHANGELOG entries, todo Creates:/scope declarations,\n' +
    'template-mirror hygiene.\n\n' +
    'Findings to classify:\n' + JSON.stringify(toCodeify, null, 2),
    { schema: SDK_SCAN_SCHEMA, label: 'sdk:scan', phase: 'Codify' }
  )

  if (!sdkScan) {
    log('WARNING: SDK issue scan returned null — this wave\'s findings were NOT classified; run /sdk-issue-scan by hand')
  } else if (sdkScan.sdkCandidates.length > 0) {
    sdkCandidatesCount = sdkScan.sdkCandidates.length
    const statuses = await candidateStatuses(sdkScan.sdkCandidates)
    const issueUrls = AUTO_FILE_SDK_ISSUES ? await fileStillOpenCandidates(sdkScan.sdkCandidates, statuses) : {}
    const candidateLines = sdkScan.sdkCandidates.map(function(c, i) {
      return '## Candidate ' + (i + 1) + ': ' + c.description + '\n' +
             '- Severity: ' + c.severity + '\n' +
             '- Component: ' + c.component + '\n' +
             '- File: ' + (c.file || 'n/a') + '\n' +
             '- Status: ' + statuses[i] + '\n' +
             (issueUrls[i] ? '- Issue: ' + issueUrls[i] + '\n' : '') +
             '- Rationale: ' + c.rationale
    }).join('\n\n')

    const wrote = await callAgent(
      'Write the file workspace/sdk-candidates.md with exactly this content:\n\n' +
      '# SDK issue candidates — ' + wave.waveId + ' (' + TODAY + ')\n\n' +
      'These critical/high findings from wave ' + wave.waveId + ' are classified as\n' +
      'SDK-level. Status is re-checked against the final tree: fixed-in-wave candidates were\n' +
      'already fixed by this wave; run `/sdk-issue-scan` on the still-open ones to file them on\n' +
      '`wailuen/a2a-sdk`. ' + (AUTO_FILE_SDK_ISSUES
        ? 'autoFileSdkIssues was on: still-open candidates carry an Issue line when filed.'
        : 'One confirmation per filing — nothing is filed automatically.') + '\n\n' +
      candidateLines,
      { label: 'sdk:candidates', phase: 'Codify', effort: 'low' }
    )
    if (!wrote) log('WARNING: workspace/sdk-candidates.md was not written (agent returned null)')
    log('SDK issue candidates: ' + sdkScan.sdkCandidates.length + ' finding(s) (' +
        statuses.filter(function(s) { return s === 'still-open' }).length + ' still-open) written to workspace/sdk-candidates.md')
    log('Run /sdk-issue-scan to file the still-open ones as GitHub issues on wailuen/a2a-sdk')
  } else {
    log('SDK issue scan: no SDK-level findings in this wave')
  }
}

if (lrnCandidates.length > 0) {
  // Up to LRN_BATCH_SIZE files per codify agent. IDs come from each finding's index in
  // lrnCandidates, never from batch position.
  const LRN_BATCH_SIZE = 5
  const lrnAssignments = lrnCandidates.map(function(f, i) {
    return { lrnId: 'LRN-' + String(lrnBase + i).padStart(3, '0'), finding: f }
  })
  const lrnBatches = []
  for (let start = 0; start < lrnAssignments.length; start += LRN_BATCH_SIZE) {
    lrnBatches.push(lrnAssignments.slice(start, start + LRN_BATCH_SIZE))
  }
  log('Writing ' + lrnAssignments.length + ' LRN file(s) in ' + lrnBatches.length + ' batch(es) of up to ' + LRN_BATCH_SIZE)

  const lrnResults = await parallel(lrnBatches.map(function(batch) {
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
        'Leave workspace/learning/README.md for the index step.\n\n' +
        entries,
        { label: 'codify:' + ids[0] + (ids.length > 1 ? '..' + ids[ids.length - 1] : ''),
          phase: 'Codify', agentType: 'codify' }
      )
    }
  }))
  const lostBatches = lrnResults.filter(function(r) { return !r }).length
  if (lostBatches > 0) log('WARNING: ' + lostBatches + ' LRN batch(es) returned null — some learnings were not written')

  const indexed = await callAgent(
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
  if (!indexed) log('WARNING: workspace/learning/README.md index was not rebuilt (agent returned null)')
}

if (registryCandidates.length > 0) {
  log('Registering ' + registryCandidates.length + ' new component candidate(s) in workspace/components/README.md')
  const registered = await callAgent(
    'Register new reusable components discovered during wave ' + wave.waveId + '.\n\n' +
    'Read workspace/components/README.md to find the highest existing C-NNN ID.\n\n' +
    'New candidates:\n' + JSON.stringify(registryCandidates, null, 2) + '\n\n' +
    'For each candidate:\n' +
    '1. Assign the next C-NNN ID (increment from highest existing)\n' +
    '2. Determine status: if the location file already exists → "present"; else → "planned"\n' +
    '3. Append ONE new row to the README.md table:\n' +
    '   | C-NNN | <name> | <location> | <status> |\n\n' +
    'Append only; existing rows stay as they are. Report: IDs assigned and their locations.',
    { label: 'registry:register', phase: 'Codify', effort: 'low' }
  )
  if (!registered) log('WARNING: component registration returned null — candidates were not registered')
}

// ─── phase 7: archive ─────────────────────────────────────────────────────────
phase('Archive')

// The suite must be green before the wave is marked complete; unknown is not green.
const preArchiveGate = await runGate('gate:pre-archive', 'Archive')
if (!preArchiveGate) {
  testsRed = true
  protocolBlocked = true
  testsBlockedArchive = true
  log('WARNING: pre-archive gate agent failed (null response) — archive BLOCKED (gate agent failed; unknown test state)')
} else if (preArchiveGate.exitCode !== 0) {
  testsRed = true
  protocolBlocked = true
  testsBlockedArchive = true
  log('Suite is RED (' + preArchiveGate.failCount + ' failing) — archive BLOCKED.')
}

if (!protocolBlocked) {
  const archiveIntent = await callAgent(
    'Run this command at the repo root exactly as written (do not edit it) and return the JSON\n' +
    'object it prints, field for field. If it fails to run, set ok=false and put its error text in error.\n\n' +
    'python3 - ' + shq(JSON.stringify(wave.allScope)) + " <<'ARCHIVE_GATE'\n" + ARCHIVE_GATE_PY + '\nARCHIVE_GATE',
    { schema: ARCHIVE_INTENT_SCHEMA, label: 'gate:archive-commit', phase: 'Archive', effort: 'low' }
  )

  const archiveKnown = archiveIntent && archiveIntent.ok === true &&
    typeof archiveIntent.templateDirExists === 'boolean' &&
    ARCHIVE_INTENT_LISTS.every(function(k) { return Array.isArray(archiveIntent[k]) })
  if (!archiveKnown) {
    protocolBlocked = true
    log('WARNING: archive-commit gate returned no trustworthy result' +
        (archiveIntent && archiveIntent.error ? ' (' + archiveIntent.error + ')' : '') +
        ' — archive BLOCKED (unknown commit state). Re-run /wave ' + wave.waveId)
  } else {
    const blocks = [
      ['offendingPaths',             'scope file(s) are uncommitted',                          'uncommitted'],
      ['offendingHarnessPaths',      'harness deliverable(s) are uncommitted',                 'uncommitted'],
      ['offendingUndeclaredImports', 'undeclared module(s) are imported by scope files',       'undeclared import'],
      ['offendingUndeclaredScope',   'tracked source file(s) are modified but undeclared',     'undeclared scope'],
    ].filter(function(b) { return archiveIntent[b[0]].length > 0 })
    if (blocks.length > 0) {
      protocolBlocked = true
      blocks.forEach(function(b) {
        log('Archive BLOCKED — ' + archiveIntent[b[0]].length + ' ' + b[1] + ':')
        archiveIntent[b[0]].forEach(function(p) { log('  [' + b[2] + '] ' + p) })
      })
      if (archiveIntent.offendingUndeclaredImports.length > 0 || archiveIntent.offendingUndeclaredScope.length > 0) {
        log('Declare the undeclared file(s) above in Creates:/Modifies: in the wave/todo.')
      }
      log('Commit or stage the files above, then re-run /wave ' + wave.waveId)
    } else {
      log('Commit check passed — all scope files and harness deliverables are committed')
    }

    // Propagation of a declared template/ deliverable cannot be verified without the checkout.
    const declaresTemplateScope = wave.allScope.some(function(p) { return p.startsWith('template/') })
    if (declaresTemplateScope && archiveIntent.templateDirExists === false) {
      protocolBlocked = true
      templatePropagationBlocked = true
      log('ARCHIVE BLOCKED — wave ' + wave.waveId + ' declares a template/ deliverable but template/ is not checked out in this working tree:')
      wave.allScope.filter(function(p) { return p.startsWith('template/') })
        .forEach(function(p) { log('  [template/ absent] ' + p) })
    }
  }
}

if (protocolBlocked) {
  // Name the actual cause; a misdirected remedy wastes developer time.
  if (testsBlockedArchive) {
    if (!preArchiveGate) {
      log('Archive SKIPPED — pre-archive gate agent failed (null response). Re-run /wave ' + wave.waveId + ' to retry.')
    } else {
      log('Archive BLOCKED — test suite RED (' + preArchiveGate.failCount + ' failing). Fix failing tests and re-run /wave ' + wave.waveId + '.')
    }
  } else if (deliverablesBlocked) {
    log('Archive SKIPPED — wave ' + wave.waveId + ' blocked: Creates: deliverables missing/unverified or a group is held at a HUMAN GATE (failed: ' + Array.from(failedGroups).join(', ') + '; pruned: ' + Array.from(prunedGroups).join(', ') + '). See workspace/todos/deferred/' + wave.waveId + '-group-*-incomplete.md / -held.md. Re-run /wave ' + wave.waveId + '.')
  } else if (implementBlocked) {
    log('Archive SKIPPED — wave ' + wave.waveId + ' blocked: at least one todo\'s implement agent died twice (see the WARNING lines above). Re-run /wave ' + wave.waveId + '.')
  } else if (templatePropagationBlocked) {
    log('Archive SKIPPED — wave ' + wave.waveId + ' declares a template/ deliverable but template/ is not checked out (see ARCHIVE BLOCKED detail above).')
    log('Clone wailuen/a2a-agent-template into template/, land the propagated file(s), then re-run /wave ' + wave.waveId + '.')
  } else if (phaseBudgetBlocked) {
    log('Archive SKIPPED — wave ' + wave.waveId + ' blocked: phase redteam round budget exhausted with surviving critical/high findings.')
    log('Fix the findings in workspace/todos/deferred/' + wave.waveId + '-phase-budget-exhausted.md, then re-run /wave ' + wave.waveId + '.')
  } else if (unitBudgetBlocked) {
    log('Archive SKIPPED — wave ' + wave.waveId + ' blocked: unit redteam round budget exhausted with surviving critical/high findings for at least one group.')
    log('Fix the findings in the affected group\'s workspace/todos/deferred/' + wave.waveId + '-group-<label>-budget-exhausted.md, then re-run /wave ' + wave.waveId + '.')
  } else if (redteamUnknownBlocked) {
    log('Archive SKIPPED — wave ' + wave.waveId + ' blocked: redteam never returned a trustworthy verdict (persistent null response or findingsCount mismatch) within its round budget.')
    log('See the workspace/todos/deferred/' + wave.waveId + '-*-rt-null-budget.md / -rt-mismatch-budget.md note(s), then re-run /wave ' + wave.waveId + '.')
  } else if (fixLoopTestsBlocked) {
    log('Archive SKIPPED — wave ' + wave.waveId + ' blocked: a fix loop stopped on a red or unknown test gate with findings unresolved.')
    log('See the workspace/todos/deferred/' + wave.waveId + '-*-tests-red-*.md / -gate-null-*.md note(s), then re-run /wave ' + wave.waveId + '.')
  } else {
    log('Archive SKIPPED — wave ' + wave.waveId + ' blocked by the protocol audit or the commit check (see BLOCKED lines above)')
    log('Fix the issues above, run /agent-verify if protocol findings were involved, then re-run /wave ' + wave.waveId)
  }
} else {
  const waveFileTag = WAVE_FILE.replace('workspace/todos/', '')
  const archived = await callAgent(
    'Archive wave ' + wave.waveId + '. Perform in order:\n\n' +
    '1. Check whether `workspace/todos/completed/' + WAVE_BASENAME + '` already exists. Parse already ' +
    'refused a colliding wave ID, so it should not; if it does (e.g. created by a concurrent process), ' +
    'STOP: never move or overwrite it. Leave `' + WAVE_FILE + '` in place, report the collision, ' +
    'and skip the rest of this step. Otherwise, move `' + WAVE_FILE + '` → `workspace/todos/completed/` (same filename).\n\n' +
    '2. In `workspace/todos/plan.md`, find the row for ' + wave.waveId + ':\n' +
    '   - If a row already exists: change [ ] to [x] and append ✅ ' + TODAY + ' after the wave title.\n' +
    '   - If NO row exists (GH-issue waves are not pre-seeded): append a new row to the Wave summary table:\n' +
    '     `| ' + wave.waveId.toUpperCase() + ' [x] ✅ ' + TODAY + ' | ' + waveFileTag + ' | G | — | — |`\n' +
    '     Adjust the Slices column if you can determine the count from the file.\n\n' +
    '3. For each path in the scope list, find the matching FR in workspace/prd/ if any.\n' +
    '   If Implementation: says [pending], replace with the real src/path:symbol.\n' +
    '   If Test: says [pending], replace with `tests/<file>.py::<test_name>` ONLY for a test that exists and passed in this wave: ' +
    'the file must be a tests/ path in the scope list below and the test name must be cited in the wave file (now at workspace/todos/completed/' + WAVE_BASENAME + ' after step 1) and defined in that file. ' +
    'Otherwise leave Test: as [pending].\n' +
    '   Scope paths (Creates: ∪ Modifies:):\n' + wave.allScope.join('\n') + '\n\n' +
    '4. Relocation sweep: for every `*-budget-exhausted.md` file in `workspace/todos/deferred/`\n' +
    '   (including this wave\'s own, if any), check whether ALL findings in it are marked RESOLVED.\n' +
    '   If so, and `workspace/todos/completed/<that file\'s basename>` does not already exist, `mv` it\n' +
    '   to `workspace/todos/completed/` (same filename); if it already exists, skip that file and\n' +
    '   report the collision. `deferred/` keeps only files with at least one OPEN finding.\n\n' +
    'Report: file moved (or the collision reported instead), plan.md updated (row updated or\n' +
    'appended), FR fields updated, and the list of any deferred markers relocated by the step-4\n' +
    'sweep (or none, or any step-4 collisions skipped).',
    { label: 'archive', phase: 'Archive' }
  )
  if (!archived) log('WARNING: archive agent returned null — verifying what landed')

  // The archive agent's report is not trusted: verify the move and the ledger row (the row
  // must name this wave's own file, since two waves can share a waveId), self-heal the row
  // once, and block as incomplete if either is still missing.
  const archiveCheckPrompt =
    'Run each command at the repo root and report the results:\n' +
    '1. grep -i ' + shq(wave.waveId) + ' workspace/todos/plan.md | grep -ci -F ' + shq(waveFileTag) + '\n' +
    '   → matchCount (the printed number; 0 if nothing printed); rowPresent = matchCount >= 1.\n' +
    '2. test -f ' + shq('workspace/todos/completed/' + WAVE_BASENAME) + ' && echo yes || echo no → archivedFileExists.\n' +
    '3. test -f ' + shq(WAVE_FILE) + ' && echo yes || echo no → activeFileExists.'
  let archiveCheck = await callAgent(archiveCheckPrompt,
    { schema: ARCHIVE_CHECK_SCHEMA, label: 'gate:archive-plan-row', phase: 'Archive', effort: 'low' })

  if (archiveCheck && archiveCheck.archivedFileExists && !archiveCheck.rowPresent) {
    log('WARNING: workspace/todos/plan.md has no row for ' + wave.waveId + ' (file ' + waveFileTag + ') after archive — self-healing')
    await callAgent(
      'workspace/todos/plan.md is missing a ledger row for wave ' + wave.waveId + ' (file ' + waveFileTag + ') even though it was ' +
      'just archived to workspace/todos/completed/. Append this exact row to the end of the Wave summary table this ' +
      'wave belongs to (columns Wave | File | Parallel group | Slices | Depends). A row for this waveId whose File ' +
      'column names a DIFFERENT file belongs to another wave that reused the ID — leave it untouched and append a ' +
      'new row for THIS wave:\n' +
      '`| ' + wave.waveId.toUpperCase() + ' [x] ✅ ' + TODAY + ' | ' + waveFileTag + ' | G | — | — |`\n' +
      'Leave every other row as it is.',
      { label: 'archive-plan-row-repair', phase: 'Archive', effort: 'low' }
    )
    archiveCheck = await callAgent(archiveCheckPrompt,
      { schema: ARCHIVE_CHECK_SCHEMA, label: 'gate:archive-plan-row-recheck', phase: 'Archive', effort: 'low' })
    if (archiveCheck && archiveCheck.rowPresent) {
      log('plan.md row for ' + wave.waveId + ' (file ' + waveFileTag + ') appended by self-heal guard')
    }
  }

  if (!archiveCheck || !archiveCheck.archivedFileExists || archiveCheck.activeFileExists || !archiveCheck.rowPresent) {
    archivePlanRowMissing = true
    log('BLOCKED — archive of ' + wave.waveId + ' is INCOMPLETE: ' + (!archiveCheck
      ? 'the verification returned null (unknown state)'
      : [!archiveCheck.archivedFileExists ? 'wave file not in workspace/todos/completed/' : null,
         archiveCheck.activeFileExists ? 'wave file still in its active location' : null,
         !archiveCheck.rowPresent ? 'no plan.md row naming ' + waveFileTag : null].filter(Boolean).join('; ')) +
      '. Finish the archive by hand, then re-run /wave ' + wave.waveId + ' to confirm.')
  } else {
    log('Wave ' + wave.waveId + ' archived — ' + lrnCandidates.length + ' LRN(s) captured')
  }
}

return {
  waveId:                wave.waveId,
  totalTodos:            totalTodos,
  lrnsCaptured:          lrnCandidates.length,
  cNnnRegistered:        registryCandidates.length,
  sdkCandidates:         sdkCandidatesCount,
  groupsExecuted:        wave.groups.length,
  planReviewRounds:      planRound,
  phaseRedteamRounds:    pRound,
  exhausted:             pRound >= PHASE_MAX_ROUNDS,
  protocolBlocked:       protocolBlocked,
  testsRed:              testsRed,
  testsBlockedArchive:   testsBlockedArchive,
  fixLoopTestsBlocked:   fixLoopTestsBlocked,
  implementBlocked:      implementBlocked,
  deliverablesBlocked:   deliverablesBlocked,
  failedGroups:          Array.from(failedGroups),
  prunedGroups:          Array.from(prunedGroups),
  archivePlanRowMissing: archivePlanRowMissing,
  unitBudgetBlocked:     unitBudgetBlocked,
  phaseBudgetBlocked:    phaseBudgetBlocked,
  redteamUnknownBlocked: redteamUnknownBlocked,
}
