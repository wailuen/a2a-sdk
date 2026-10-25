---
id: LRN-531
title: CHANGELOG must name files by repo path, not class names
category: ops
severity: high
source: redteam
date: 2026-10-25
---

## What happened
The GH-256 CHANGELOG bullet never named agent_sdk/testing/chat.py or agent_sdk/testing/mcp.py, and named turns.py only by short name. New helpers `ChatDriver.a2ui_client_activation()` and `card_catalog_ids()` were not tied to their file.

## Root cause
The bullet named classes (ChatDriver, McpClient), which do not satisfy the LRN-491 file-path check.

## Check
For each of turns.py, chat.py, mcp.py, run `grep -c 'agent_sdk/testing/<name>' CHANGELOG.md` over [Unreleased] and confirm >= 1.

## Prevention
When planning a CHANGELOG entry, require the full repo path of each changed agent_sdk/ file, and tie each new export to its file. A class name does not count.
