---
id: LRN-401
title: Skill says load secret without showing how
category: security
severity: high
source: redteam
date: 2026-10-16
---

## What happened
The mint block needed BASE_URL, ADMIN_KEY, SERVICE_KEY_FILE and KEY_LABEL in os.environ, but the prose only said "load ADMIN_KEY without printing it". Each Bash call is a fresh shell, so the agent would inline the literal key (transcript leak) or use unexported variables, causing a KeyError after the key was minted. The test hid this by passing a fully exported env.

## Root cause
No same-command loader was documented, and the test harness supplied state the real agent shell would not have.

## Check
Test: run the mint block with non-exported shell variables and assert it works. Assert the documented ADMIN_KEY loader never prints the key. `grep -n "export ADMIN_KEY" harness/skills/*/SKILL.md`.

## Prevention
When planning a skill command that needs a secret, require a self-contained block that exports and loads every variable in the same command. Tests must run it with a clean environment.
