---
id: LRN-442
title: Verify where a foreign protocol field sits in its published schema
category: protocol
severity: high
source: redteam
date: 2026-10-22
---

## What happened
GH-213 read `supportedCatalogIds` at the root of `a2uiClientCapabilities`. The A2UI v0.9.1 schema (client_capabilities.json) nests it under a required `"v0.9"` key, so spec-following clients still fell back to `[CATALOG_ID]`. Docs and CHANGELOG claimed the upstream key was accepted.

## Root cause
The field was accepted from memory of its name, without checking its location in the upstream JSON schema.

## Check
Run `grep -n '"v0.9"' agent_sdk/a2ui/translator.py` and confirm a nested-shape test exists in tests/ for `from_metadata`.

## Prevention
When planning acceptance of another protocol's field, cite the schema file and JSON path, and add a test using the exact spec-shaped payload.
