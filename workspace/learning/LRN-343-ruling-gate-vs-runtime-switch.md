---
id: LRN-343
title: Ruling condition not mapped to real runtime switch
category: ops
severity: high
source: redteam
date: 2026-10-13
---

## What happened
The GH-162 ruling says to warn when a shared store is configured with OAuth on. The OAuth server is always mounted and MCP sessions are per-process in every auth mode. _warn_single_replica_required only fired for oauth_idp=='oidc' or one-time consent, and docs/deployment.md told operators API-key-only could use many replicas.

## Root cause
The ruling's 'OAuth on' was read as a setting, but no such switch exists; the feature is always mounted.

## Check
Verify a test with Azure Table backend and default OAuth mode yields exactly one WARNING. Verify docs/deployment.md says any deployment serving /mcp or OAuth connectors needs one replica.

## Prevention
When planning, map each 'X is on' condition in a ruling to the real runtime switch. If the feature is always mounted, make the gate unconditional unless the maintainer ratifies a narrower one.
