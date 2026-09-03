---
id: LRN-180
title: Wave scope extraction drops paths embedded in Creates:/Modifies: prose
category: sdk
severity: high
source: redteam
date: 2026-08-15
---

## What happened
The Parse-phase prompt in wave-cycle.js asked for "every `Creates:`/`Modifies:` path
listed," but todos commonly write `Creates: (modifies \`a\`, \`b\`); adds \`c\``
with no separate `Modifies:` field. Extraction only caught bare-line paths, so
~20 of 30 declared deliverables were dropped from `wave.allScope`, silently
narrowing phase redteam, protocol-surface detection, the template hard-block,
and `offendingUndeclaredScope`.

## Root cause
Scope extraction pattern-matches paths on `Creates:`/`Modifies:` lines
positionally, not by scanning for every backticked path token anywhere on
those lines — so paths inside parenthetical `(modifies a, b, c)` prose are
invisible to it.

## Check
Feed a fixture todo using `Creates: (modifies \`a\`, \`b\`, \`c\`); adds \`d\`` form
and assert every backticked path lands in `allCreates ∪ allModifies` —
`tests/test_workflow_sync.py`. Also:
`grep -n "every 'Creates:' path listed" .claude/workflows/*.js template/.claude/workflows/*.js`
must show updated wording, not the old positional instruction.

## Prevention
When planning wave-runner scope-extraction changes, require harvesting EVERY
backticked repo-relative path on a `Creates:`/`Modifies:` line — including
inside parenthetical `(modifies ...)` prose and trailing `adds ...` clauses —
not just a leading bare path. Apply identically across all wave-runner
mirrors (`.claude/workflows/wave-cycle.js`, `harness/workflows/wave-cycle.js`,
`template/.claude/workflows/wave-cycle.js`, `sdk-wave.js`).
