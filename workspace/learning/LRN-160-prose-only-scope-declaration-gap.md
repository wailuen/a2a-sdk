---
id: LRN-160
title: Files named only in Reuses:/SI: prose evade wave scope and all gates
category: sdk
severity: high
source: redteam
date: 2026-08-15
---

## What happened
Five tracked files (mcp.py, admin.py, __init__.py, redact.py, wave/SKILL.md)
were modified by a wave but named only in todos' Reuses:/SI: prose, never on
a Creates:/Modifies: line. Tracked and outside wave.allScope and harness
dirs, they evaded offendingPaths, offendingHarnessPaths, AND
offendingUndeclaredImports (untracked-.py only) — the triple blind spot
LRN-053/059/078 close, recurring in the wave that widened the harness dir
list for it.

## Root cause
A file named in SI/Reuses prose was treated as declared scope, but only
Creates:/Modifies: lines feed wave.allScope, so the annotation's obligation
had no gate checking it.

## Check
Grep each todo's Reuses:/SI: prose for file paths; confirm each also
appears on that todo's own Creates:/Modifies: line. No automated gate
enforces this yet — verify by hand until offendingUndeclaredScope lands.

## Prevention
When an SI/Reuses note names a file that must change, add that path to
Creates:/Modifies: at planning time, never prose-only. Add an
offendingUndeclaredScope check to the archive-commit gate (all four
runners): flag any dirty tracked agent_sdk/**.py path absent from
wave.allScope.
