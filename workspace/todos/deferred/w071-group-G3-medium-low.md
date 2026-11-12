# w071 — deferred medium/low findings (unit:G3)

- Wave: w071
- Scope: unit:G3
- Date: 2026-11-10

Non-blocking — these did not block w071's archive. Address opportunistically or fold into a future wave.

## RT-001 (medium) — harness/workflows/wave-cycle.js:1557

Quote: `const openTodos = function(g) { return g.todos.filter(function(t) { return !(t && t.done === true) }) }`

The tier loop never drops a todo the scan marks skip: true. If the parse model puts a [~] todo in a group, that todo still goes to an implementer. A probe (BASE_MD plus a [~] `S-1` in group A, included in the model's groups) dispatched impl:A-1, impl:S-1 and impl:B-1. The AC says dispatch drops skip todos, and the CHANGELOG says dispatch still ignores them, but in fact this depends only on the model following the 'Skip todos marked [~]' prompt line. The same code is in .claude/workflows/sdk-wave.js:1552 and the byte-identical copies.

- Fix: In parseWave, build skipIds from pf.todoFacts and remove those todos from each g.todos before computing g.held, g.done and the tier dispatch. Or filter skip ids in openTodos and in the done/held sets. Add a test where the scripted parse result includes a [~] todo, and assert that no impl:<skip id> agent runs. Today's test 11 only covers a model that already leaves it out.
- Codify: Once the deterministic scan exposes a flag (skip/done/held), the runner must enforce it on the model's groups itself, never trust the model to have left the todo out.
- SDK candidate: yes

## RT-002 (medium) — harness/agents/core/planner.md:44

Quote: `  - Depends: P0-01`

The planner's own todo example still writes Depends: without backticks. The new dangling-depends check only looks at backticked, id-shaped tokens, so a planner that copies the example writes ids the check never sees. A probe with 'Depends: A-1, Z-9' (Z-9 not in the file) gave no dangling-depends; deriveGroupDeps silently dropped Z-9 and the run went on. This is the GH-279 root cause (a missing Depends: id silently dropped). Line 63's inline example also uses escaped backticks inside a code span, which reads badly. Same in .claude/agents/core/planner.md and template/.claude/agents/core/planner.md.

- Fix: Change the example to '  - Depends: `P0-01`' and rewrite line 63 without backslash-escaped backticks inside a code span. Update all three planner.md copies at once to keep them byte-identical. Also consider having the dangling check fail closed on a Depends: line that names an id-shaped token without backticks, so the old format cannot silently bypass it.
- Codify: When a runner check depends on a field format, the planner's own example must use that exact format, or every plan made from the example bypasses the check.
- SDK candidate: yes

## RT-003 (low) — CHANGELOG.md:11

The GH-279 entry does not name every changed harness/ file by its full repo path, which the wave header requires (LRN-491 as extended to harness/). It writes 'the three `wave` `SKILL.md` copies, the three `planner.md` copies' instead of harness/skills/wave/SKILL.md, harness/agents/core/planner.md and their .claude/ copies. It also says dispatch ignores [~] todos, which RT-001 shows is not enforced by the runner.

- Fix: List harness/skills/wave/SKILL.md, .claude/skills/wave/SKILL.md, harness/agents/core/planner.md and .claude/agents/core/planner.md by full path. After RT-001 is fixed, reword the dispatch claim so it matches what the code does.
- SDK candidate: yes

Resolved 2026-11-12: all findings fixed by hand before release.
