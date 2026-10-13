---
id: LRN-313
title: Reversed conformance rule left in other skill phrasings
category: protocol
severity: high
source: redteam
date: 2026-10-13
---

## What happened
GH-158 made `parentMessageId` optional and fixed the ag-ui-check table row only. The conformance-traps list still said "Missing `parent_message_id` on tool calls" in both SKILL.md copies. A later audit would flag the SDK's tool-first TOOL_CALL_START frames as a defect, reopening the superseded "always emit null" rule.

## Root cause
The fix patched the one line the issue cited, not every phrasing of the old rule.

## Check
`grep -rn "Missing \`parent_message_id\`\|Missing \`parentMessageId\`" .claude/skills harness/skills template/.claude/skills` returns no match.

## Prevention
When planning a ruling that reverses a conformance rule, include a task to grep all phrasings (camelCase, snake_case, tables, trap lists) across every skill, advisor and template copy, plus a test that greps for the old text.
