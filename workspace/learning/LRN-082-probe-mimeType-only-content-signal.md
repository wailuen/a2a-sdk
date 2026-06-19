---
id: LRN-074
title: A2A probes using only mimeType miss ContentModel DataPart content-type signals
category: testing
severity: high
source: redteam
date: 2026-06-15
---

## What happened
The acceptance harness A2A probe (`acceptance-api.js:138-141`) extracted content types exclusively from `part["metadata"]["mimeType"]`. When no `X-A2A-Extensions` header is sent, A2UI is inactive and `runner.py:171` emits `ContentModel` DataPart metadata as `{data_type, tool_name}` with no `mimeType` field. Every A2A probe run therefore recorded `contentTypes=[]`, making the rubric criterion "correct content type emitted" permanently unachievable on A2A and generating false transport-divergence and content-type-gap findings.

## Root cause
The probe assumed A2UI's `mimeType` is the sole content-type signal, but the SDK runner uses `data_type` (metadata field) and artifact `name` (`runner.py:193`) as the structured identifier when A2UI is inactive.

## Check
`grep -n "mimeType" harness/workflows/acceptance-api.js` — confirm the extraction block also reads `part.metadata.data_type` and/or the enclosing artifact's `name` field; absence of both secondary reads is the defect.

## Prevention
When planning acceptance probes that score content-type emission over A2A, ensure the probe collects content-type signals from at least two sources: `part.metadata.mimeType` (A2UI active path) AND `part.metadata.data_type` / artifact `name` (SDK ContentModel path). Never rely on a single metadata field whose population is conditional on an extension header the probe itself does not send.
