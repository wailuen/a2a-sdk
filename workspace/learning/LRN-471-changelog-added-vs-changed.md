---
id: LRN-471
title: New public API filed under Changed; files not named
category: ops
severity: high
source: redteam
date: 2026-10-23
---

## What happened
New public API (Agent(mcp_skills=), McpTestClient, McpClient.list_prompts/get_prompt, SkillsRegistry.listed, @tool(mcp_description=)) was filed under `### Changed`. The GH-206 entry did not name config.py, routes/mcp.py, docs/deployment.md, docs/protocols.md or the registry row.

## Root cause
Authors treated additive opt-in features as changes and skipped the per-file list.

## Check
For each new public symbol, grep CHANGELOG.md and confirm it sits under `### Added`. Confirm every changed agent_sdk basename appears in its entry (LRN-379).

## Prevention
When planning a CHANGELOG task, require new kwargs/methods/aliases under ### Added and a "Changed:" list naming every touched file.
