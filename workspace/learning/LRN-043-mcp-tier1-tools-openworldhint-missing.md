---
id: LRN-043
title: openWorldHint must be derived from SourceAdapter backing, not tier or read_only
category: protocol
severity: high
source: redteam
date: 2026-06-17
updated: 2026-08-15
---

## What happened
Two successive versions of this annotation were wrong in opposite directions.

First, tools were registered with no `openWorldHint` at all. MCP 2025-06-18
defaults an absent `openWorldHint` to **true**, so every unannotated tool read as
open-world and clients applying annotation-driven safety UI over-confirmed on
tools that never leave the process.

GH-52 (w016) then seeded `openWorldHint=False` whenever `tier == 1` or
`read_only=True`. That was also wrong, and more dangerously so: it is a claim
about the tool's *dispatch class*, not about what the tool reaches. A tier-1
read-only tool that queries an external system through a `SourceAdapter` is
open-world by definition, and GH-52 asserted the opposite to every MCP client —
under-warning on exactly the tools that do talk to the outside world.

GH-134 replaced both with a derivation from the only fact that answers the
question: does this tool actually reach an external system?

## Root cause
The annotation was seeded from whatever was already in scope at the decorator
call (`tier`, `read_only`) instead of from the property it describes. Both
inputs correlate loosely with open-worldness and neither determines it, so the
seed was right for the common case and silently wrong for the case that matters.

## Landed rule (GH-134)
`agent_sdk/agent/registry.py` seeds, in `decorator()` once the signature has been
inspected:

```python
resolved_annotations["openWorldHint"] = bool(adapter_params)
```

- **True iff** the tool declares at least one `SourceAdapter`-backed
  keyword-only parameter (`adapter_params` is non-empty).
- Independent of `tier` and of `read_only` — a tier-1 read-only adapter-backed
  tool gets `openWorldHint=True`; a tier-2 non-adapter tool gets `False`.
- An explicit `annotations={"openWorldHint": ...}` on `@tool` still wins: the
  seed is applied before `resolved_annotations.update(annotations or {})`.
- `readOnlyHint`/`destructiveHint` are unaffected — they are still seeded from
  `read_only` in `base_annotations`.
- Because the key is now seeded unconditionally, `decl.annotations` is never
  empty and never `None` (RT-015).

## Check
```
grep -n 'resolved_annotations\["openWorldHint"\] = bool(adapter_params)' \
  agent_sdk/agent/registry.py
```
One match required. Zero matches means the derivation was removed or reverted to
a tier/read_only seed — re-read this learning before changing it.

Behavioural pins (all must pass):
```
pytest -q tests/test_mcp_conformance_w9.py -k sc_c8
```
- `test_sc_c8_tier1_non_adapter_tool_open_world_hint_false`
- `test_sc_c8_tier1_adapter_backed_tool_open_world_hint_true`
- `test_sc_c8_tier2_adapter_backed_tool_open_world_hint_true`

## Why `False` is a claim, not a guess
Every review pass since GH-134 has re-raised the same objection: `adapter_params`
being empty proves the tool declares no adapter, not that it never reaches out —
so seeding `False` looks like asserting closed-world on an unknown, in the
under-warning direction this learning says is the dangerous one.

It is not an unknown. The SDK's dependency-injection contract is that a tool
receives external capability **only** as an SDK-instantiated `SourceAdapter`
passed by typed keyword-only parameter — there is no ambient handle by any other
route. `agent_sdk/contrib/commitments/source.py`'s module docstring states it
outright ("A tool can only receive SDK-instantiated `SourceAdapter` instances (by
typed keyword param) or its own pydantic input — there is no ambient handle to
the commitment store"), and that rule is exactly why `CommitmentsSource` is a
`SourceAdapter` instead of a module-level singleton. `ToolSet.tool()`'s signature
walk enforces the injection side: every keyword-only parameter must be a
`SourceAdapter` subclass or carry a default, and `*args`/`**kwargs` are rejected.

So `adapter_params` is the complete record of a tool's **declared** reach, and
`openWorldHint=False` is a claim about the declared contract that the SDK can
stand behind. A body that smuggles I/O in past the contract (Python enforces no
capabilities) is a contract violation to fix at the tool, not a case the
annotation should hedge for — and the author's escape hatch is one keyword away:
`annotations={"openWorldHint": True}` wins over the seed.

Do not "fix" this by leaving the key absent for adapter-free tools. That is the
pre-GH-52 state this learning opens by describing: absent means MCP's default
`true`, which over-warns on every in-process tool.

## Prevention
Derive a protocol annotation from the property it asserts, never from a
correlated field that happens to be in scope. `openWorldHint` describes reach,
so it is computed from `adapter_params` — the signature-level fact that records
reach — not from `tier` (a dispatch class) or `read_only` (a mutation class).

Corollary, learned from this annotation costing three rounds of the same
re-litigation: when a derivation is complete only because of an invariant stated
somewhere else in the codebase, cite that invariant AT the derivation. A reviewer
who cannot see why the negative case is sound will re-open it every pass, and
each re-opening looks like a fresh finding.

Cross-references: GH-52 (original, wrong seed) → GH-134 (correction);
LRN-066 (a wave that changes how a live learning's Check is satisfied must
rewrite that Check in the same change — this file is that rewrite).
