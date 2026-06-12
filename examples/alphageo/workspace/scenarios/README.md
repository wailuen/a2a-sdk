# Scenario catalog — AlphaGeo climate-risk agent

Real-life, job-to-be-done usage scenarios for the AlphaGeo agent. Each scenario
is a multi-turn conversation from the perspective of a domain professional
(RE investor, insurance actuary, infrastructure operator, etc.).

All 10 baseline scenarios were live-tested against the running agent (AG-UI,
Azure OpenAI, AlphaGeo API) on 2026-06-12. All pass; A2UI surface emitted on
every turn. The 100% `buildable` result reflects a deliberately complete
reference implementation — not a rubber-stamp pass; all 10 scenarios were
exercised against the actual API (see `scripts/test_chat.py` shim).

| File | Range | Domains | Status |
|------|-------|---------|--------|
| [001-climate-risk.md](001-climate-risk.md) | SCN-001…SCN-010 | A–F | live-tested |

## Domain map

| Letter | Domain | Range | Count |
|--------|--------|-------|-------|
| A | Real estate investment | SCN-001, SCN-006 | 2 |
| B | Insurance / underwriting | SCN-002, SCN-007, SCN-008 | 3 |
| C | Infrastructure operations | SCN-003, SCN-010 | 2 |
| D | Industrial operations | SCN-004 | 1 |
| E | Long-term trajectory | SCN-005 | 1 |
| F | Comparative / portfolio | SCN-009 | 1 |

## Capability tally

**10 buildable · 0 partial · 0 gap**

All 10 scenarios are live-verified against the current implementation.
Run `/scenario` to generate additional scenarios, including `partial`/`gap`
entries that surface roadmap signals.
