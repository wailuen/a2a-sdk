# SDK issue candidates — w038 (2026-07-25)

**RESOLVED, archived 2026-07-25 — do not file.** A later iteration within the same
w038 run fixed this before archival: `~/.claude/agents/a2ui-advisor.md` (+ its
`.claude/agents/` and `harness/agents/` mirrors) now states the A2UI v0.9.1 bare-array
binding neutrally alongside the SDK's own `data.messages` deviation, and the
independent A2UI-advisor conformance audit run during the 0.5.44 `/sdk-test` re-check
(2026-07-25) confirmed the oracle is not corrupted/self-contradictory. See LRN-134/LRN-135.
Kept here (renamed from `sdk-candidates.md`) for the historical record only — the
original candidate text below reflects a defect that no longer exists.

~~Run `/sdk-issue-scan` to review and file as GitHub issues on `wailuen/a2a-sdk`.~~

## Candidate 1: GH-128's fix to the a2ui-advisor spec oracle (lines ~729-733, 785-787, 865-867) rewrote the portable A2UI-over-A2A conformance rule to teach this SDK's private `data.messages` object wrapper as THE spec requirement, asserting a bare array 'fails schema validation against a spec-conformant A2A client.' This contradicts A2UI v0.9.1's own A2A binding (which mandates `data` be a bare array) and contradicts the wave's own LRN-134, which verifies byte-verbatim from the pinned spec that no published spec defines `data.messages`. Because a2ui-advisor is the portable, project-agnostic oracle invoked by the a2ui-check skill against ANY project (not just this SDK), a genuinely spec-conformant third-party project emitting the correct bare array is now told by the oracle that its correct output is a protocol violation, steering it toward adopting this SDK's non-interoperable wire shape.
- Severity: high
- Component: harness/agent
- File: /Users/wailuen/.claude/agents/a2ui-advisor.md
- Rationale: a2ui-advisor.md is a harness advisor agent definition (under .claude/agents/, invoked by the a2ui-check skill) — shared conformance-oracle infrastructure used across every agent built on the SDK, not agent-specific tool code or a domain adapter, so it is squarely SDK-level. The specific defect is that a shared, portable spec-conformance reference was overwritten with one implementation's private deviation presented as the canonical rule, corrupting the oracle for all future/other consumers of the a2ui-check skill. Recommended fix: restore the A2UI v0.9.1 bare-array binding as the spec rule (matching LRN-134), and document the SDK's `data.messages` wrapper only as a clearly-labeled, non-canonical deviation with its own rationale — never as the enforced rule.
