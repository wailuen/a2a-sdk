---
id: LRN-099
title: "A2A REST action suffix can differ from the JSON-RPC method name"
category: protocol
severity: high
tags: [a2a, conformance, spec-reading]
wave: w022
---

The A2A HTTP+JSON binding maps JSON-RPC method names to REST paths, but the REST action suffix is NOT always the last segment of the method name.

**Concrete case:** `tasks/resubscribe` → `POST /v1/tasks/{id}:subscribe` (not `:resubscribe`). The action suffix `:subscribe` describes what the endpoint does (opens/reconnects an SSE subscription); the method name `resubscribe` carries the semantic distinction between initial subscribe and reconnect.

**How the error happened:** GH-75 was filed based on reading the method name (`tasks/resubscribe`) and assuming the REST suffix would match (`:resubscribe`). The actual transport table (§2) and §3.5.6 both list `:subscribe` for this method. The issue claim was unverified against the actual transport table.

**Guard:** When a todo claims a route rename is required for spec compliance, always verify against BOTH the transport table (§2) and the HTTP+JSON binding section. Reading the method name alone is insufficient. The local spec digest at `.claude/reference/a2a-protocol-0_3_0.md` §2 is the authoritative lookup.
