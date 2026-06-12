---
name: analyze
category: core
description: "Create or update PRD, ADR, todos, and spec documents in workspace/ — compact, machine-scannable, context-optimised. Uses Opus."
---

# /analyze — Spec document management

Create or update specification documents under `workspace/`. The primary
audience is the Claude Code session itself: documents are written in a format
that `/scenario` and `/codify` can scan mechanically.

## Usage

```
/analyze <action> [target]
```

Actions:
- `create prd` — generate a new PRD section from current context
- `update prd` — revise an existing PRD to reflect new scope
- `update adr` — append new ADRs for recent decisions
- `update todos` — refresh the phased work-item list
- `audit` — check all workspace docs for staleness, conflicts, and size budget

Examples:
- `/analyze create prd` (generate FR/NFR from research + locked decisions)
- `/analyze update adr` (append ADRs for decisions made since last update)
- `/analyze update todos` (reconcile todos against current PRD and code state)
- `/analyze audit` (full workspace health check — find orphaned FRs, stale ADRs)

## Steps

1. Parse `$ARGUMENTS` to determine action (`create` / `update` / `audit`) and target
   (`prd` / `adr` / `todos`).
2. Read existing files in the relevant `workspace/` subdirectory so the new
   content extends rather than duplicates — note the highest existing sequence
   number.
3. Read the current code state relevant to the action:
   - For `prd`: read `src/tools/`, `src/content.py`, any recent session context
     about requirements decisions.
   - For `adr`: read recent session context for any decisions that lack a record;
     check existing ADRs for superseded status.
   - For `todos`: read existing PRD FRs and compare `Implementation: [pending]`
     items against actual code presence.
4. Produce the document(s) following the format specs below.
5. Write to the appropriate subdirectory using the naming convention. Every new
   file is under 3 KB; if content would exceed that, split into numbered parts.
6. Update the subdirectory `README.md` index (append rows; do not rewrite
   existing rows unless they are factually wrong).
7. For `audit`: read all workspace files; report findings as `[STALE]`,
   `[CONFLICT]`, or `[ORPHAN]` with file + line; fix what is unambiguous; flag
   the rest for the user.
8. Report back: what was created or changed, and any items flagged for the user.

## FR / NFR format (mechanically checkable)

Every requirement in `workspace/prd/` must follow this format so the session
can verify spec ↔ code mechanically:

```markdown
**FR-N.** <one-sentence requirement> (ADR-X, ADR-Y)

- <acceptance criterion 1 — testable>
- <acceptance criterion 2 — testable>
- **Implementation:** `src/<path>/<file>.py:<symbol>` *(or `[pending]`)*
- **Reuses:** `C-NNN` *(from `workspace/components/README.md`; omit if none)*
- **Test:** `tests/<file>.py::<test_name>` *(or `[pending]`)*
```

- `[pending]` is the expected state before implementation; replace with the
  landed path once code is merged.
- `ADR-X` in FR cross-references uses the display label (`ADR-1`, `ADR-12`),
  not the filename prefix (`a001`). The two forms are equivalent; the filename
  is the canonical key when looking up the file.
- Same template for NFRs (substitute `NFR-N`).

## ADR format

```markdown
# ADR a[NNN] — Title

- **Status:** Proposed | Accepted | Superseded by a[MMM]
- **Date:** YYYY-MM-DD

## Context
<why this decision was needed>

## Decision
<what was decided>

## Consequences
<what changes, what is now possible, what is now harder>
```

## Todo format

```markdown
# Phase w[NNN] — Title

- **Status:** pending | in-progress | done
- **Requires:** FR-N, FR-M *(omit if standalone)*

## Items

- [ ] <specific, verifiable work item>
- [ ] <specific, verifiable work item>
```

## Naming conventions

| Doc type | Pattern | Example |
|----------|---------|---------|
| PRD section | `p[NNN]-[description].md` | `p001-climate-risk-report.md` |
| ADR | `a[NNN]-[description].md` | `a001-credential-architecture.md` |
| Todo phase | `w[NNN]-[description].md` | `w001-source-adapter.md` |
| Learning | `LRN-[NNN]-[description].md` | `LRN-001-credential-regex.md` |

`[NNN]` is zero-padded sequential. Scan the target directory for the highest
existing number and increment.

## Audit rules (`/analyze audit`)

An audit flags:
- PRD FRs with `Implementation: [pending]` but code already exists (stale pending)
- PRD FRs referencing an ADR that no longer exists or has been superseded
- ADRs with `Status: Proposed` older than 30 days (likely stale)
- Todos referencing FRs that were removed
- `workspace/components/README.md` entries pointing to nonexistent source paths
- Learning files that lack `id:` or `severity:` in their frontmatter

Report each finding as `[STALE]`, `[CONFLICT]`, or `[ORPHAN]` with the
specific file + line.

## Hand-offs

- New FRs → `/add-tool` or `/add-source` to implement them
- Confirmed implementation gaps → `/scenario` to generate realistic test cases
- Audit findings → fix inline or escalate to user if a decision is needed
