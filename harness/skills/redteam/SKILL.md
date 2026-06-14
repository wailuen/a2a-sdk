---
name: redteam
category: core
description: "Adversarial critique of agent-sdk agent code against spec — finds gaps, drift, SDK invariant violations, and security issues. Auto-codifies critical/high findings. Uses Opus."
---

# /redteam — Adversarial Review

Launch an adversarial review of the agent codebase against the spec.

## Usage

```
/redteam [scope]
```

Examples:
- `/redteam` — full review, all 8 dimensions + learning checks
- `/redteam security` — SDK Security Invariants (SI-1…SI-7) only
- `/redteam w001` — review Wave w001 code against its todo ACs
- `/redteam src/tools/climate.py` — review a specific file against its FR

## Steps

1. Parse `$ARGUMENTS` for optional scope.
2. Launch the `redteam` agent (Opus) with:
   - The scope (or "full" if none given)
   - Pointers to: `workspace/prd/`, `workspace/adr/`,
     `workspace/learning/README.md`, `workspace/components/README.md`,
     `src/`, `workspace/todos/`
3. Wait for the report (8 dimensions: spec↔code, SDK Security Invariants,
   operational readiness, code quality, todo↔code, plan structure, learning
   checks, component reuse). The **security** dimension runs all SI-1…SI-7
   checks and **fails closed** on any item it cannot positively confirm.
4. Display: Critical → High → Medium → Low → Clean
5. **Auto-codify**: for each critical/high finding with a `Codify:` line,
   invoke `/codify` with that summary. Assign LRN IDs in parallel.
6. Report: finding counts + learnings captured.

## SDK Security Invariants (fail closed)

The `security` dimension verifies every applicable item. An item that cannot
be positively confirmed from code is a **finding**, not a pass.

| ID | Invariant | Severity |
|----|-----------|----------|
| SI-1 | No raw `httpx`/`aiohttp`/`requests` in `src/tools/` — all HTTP through `SourceAdapter` | Critical |
| SI-2 | Exception text never interpolates credentials, tokens, or user inputs | Critical |
| SI-3 | URL path variables go through `url_segment()`/`safe_id()` inside adapters | High |
| SI-4 | Credentials via `self.credential("field")` only — no env reads in tools/adapters | High |
| SI-5 | All endpoints (except `/.well-known/`, `/health`) require auth (`require_identity`) | Critical |
| SI-6 | Upstream vendor keys never in `.env`, argv, or logs — credential store only | Critical |
| SI-7 | Every `SourceAdapter` declares non-empty `allowed_hosts` (no wildcard) | High |

All critical/high SI findings get a `Codify:` line so they become permanent
learnings that block future regressions.

## Integration

- Auto-invoked at the end of `/todos` (reviews the plan until zero critiques)
- Auto-invoked at the end of every `/wave` unit and phase
- Auto-invoked at the end of `/implement` on landed code
- Standalone at any time

## Pre-release scope rule (LRN-002)

When `/redteam` is invoked as part of a **release gate** (not a single-wave review),
it MUST run at full scope with **no scope argument**. A scoped redteam (e.g.
`/redteam w006`) only covers changed code — pre-existing protocol surface regressions
will not be detected (this is how GH #4–#8 slipped through the 0.4.0 release gate).
Full scope is the only safe pre-release posture.
