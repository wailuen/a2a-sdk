---
id: LRN-535
title: Testing-client change needs Added and Breaking entries, not only Fixed
category: ops
severity: high
source: redteam
date: 2026-10-25
---

## What happened
The GH-256 entry sat only under `### Fixed`. It added `ChatDriver.a2ui_client_activation()` and `card_catalog_ids()`. It also made `McpClient.initialize` raise for an out-of-range version (an empty string now raises too) and stopped the A2UI header being sent to agents whose card lacks the extension.

## Root cause
The change was treated as a bug fix. New API and newly-failing calls were not classified (LRN-506, LRN-507, LRN-510).

## Check
In [Unreleased] of `CHANGELOG.md`, confirm `### Added` names `agent_sdk/testing/chat.py` symbols. Confirm a Breaking/Changed entry covers the McpClient rejection with a ruling URL and `**Migration:**` line, or a provisional-surface notice.

## Prevention
When planning a testing-client change, list each new public symbol and each call that now raises. Require an Added entry and a Breaking/Changed entry for them. Keep only the bug fixes under Fixed.
