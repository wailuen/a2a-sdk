---
id: LRN-399
title: Cleanup step deletes the only copy of a secret
category: ops
severity: high
source: redteam
date: 2026-10-16
---

## What happened
The service key moved from agent context into SERVICE_KEY_FILE. The acceptance skill still unlinked that file after the first Workflow call. Every fix-loop re-run and Phase 2B then read a deleted file and failed, burning all 5 rounds.

## Root cause
A cleanup written for a regenerable file became data loss once the file was the only copy of the secret.

## Check
`grep -n "unlinkSync" harness/skills/acceptance/SKILL.md` must show no match in the Workflow invocation block. The file is removed only in the "Service key teardown" section. Test: tests/test_gh183_184_service_key_mint_step.py asserts this.

## Prevention
When planning a change that moves a secret from context into a file, list every later step that reads it. Delete the file only at the true exit points (teardown), never after the first consumer.
