---
id: LRN-335
title: Byte-identical local mirror is not delivery to template
category: ops
severity: high
source: redteam
date: 2026-10-13
---

## What happened
The RT-003 SHARED_TREE_GIT_BAN hunk in `template/.claude/workflows/wave-cycle.js` stayed uncommitted and unpushed. Local harness, .claude and template copies matched, so `test_gh164_workflow_copies_are_byte_identical` passed. Origin main of wailuen/a2a-agent-template (058a317) lacked the hunk.

## Root cause
The mirror test compares local files only; template is a peer repo (LRN-071) whose remote state is never checked.

## Check
Run `git -C template status --short` and confirm it is empty. Run `git -C template diff origin/main -- .claude/workflows/wave-cycle.js` and confirm it is empty.

## Prevention
When planning any edit to harness workflows, skills or agents, add a todo step to commit and push the template copy, and a gate that template is clean against origin/main. Do not accept the byte-identical test as proof of delivery.
