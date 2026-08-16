---
id: LRN-184
title: Ported gate logic keeps source runner's source-root literal, not destination's
category: sdk
severity: high
source: redteam
date: 2026-08-15
---

## What happened
wave-cycle.js's GH-118/LRN-119 import cross-check (step 5, ~lines 2057-2145, plus the
`offendingUndeclaredImports` schema description) was ported verbatim from sdk-wave.js and
still resolves absolute imports rooted at `agent_sdk` (58 occurrences vs 5 `src/`). But
wave-cycle.js now runs downstream agent repos only (`wrongRunnerForRepoLayout` hard-abort,
line 622-633), whose source root is `src/`. The absolute-import half of the gate is a
permanent no-op there, reopening the exact LRN-119 ImportError-at-boot class. The sibling
field `offendingUndeclaredScope` was correctly re-dialected to `src/**.py` in the same wave
(comment lines 384-397) — this field was missed. The test
`test_gh118_archive_intent_prompt_contains_import_cross_check_instructions` pins the bug by
asserting the literal "agent_sdk" against both runners.

## Root cause
Porting gate prose between wave runners copied the text but did not re-parameterize the
source-root literal to the destination runner's directory layout, and no test asserted each
runner against its own dialect.

## Check
`grep -c "agent_sdk" .claude/workflows/wave-cycle.js` in the step-5/`offendingUndeclaredImports`
region must be 0 (only `src/` literals allowed there); confirm
`test_gh118_archive_intent_prompt_contains_import_cross_check_instructions` is
dialect-parametrized `[(SDK_WAVE, "agent_sdk"), (WAVE_CYCLE_RUNTIME, "src")]`, not a shared
"agent_sdk" assertion over both runners.

## Prevention
When planning a fix or gate that ports prose/logic between wave runners with different
directory layouts, require the planner to enumerate every source-root literal in the ported
text and re-dialect each one to the destination runner's tree (not just the field a reviewer
happened to notice), and require the pinning test to be dialect-parametrized per runner rather
than asserting one literal against all runners.
