---
id: LRN-207
title: Git-dirty file outside declared scope escapes review
category: sdk
severity: high
source: redteam
date: 2026-08-19
---

## What happened
w040 group G's todo scoped only `routes/a2a.py`/`mcp.py`, but the diff also
left `tasks/store.py`/`memory.py` (new public `owner_task` attr, reaping in
`subscribe`) plus docs (DESIGN.md, protocols.md, a SKILL.md, CHANGELOG.md)
dirty with no Creates:/Modifies: line — escaping the undeclared-scope gate.

## Root cause
Scope discipline (LRN-053/168/202) was checked only against .py files the
request named; doc/skill/CHANGELOG files touched as side effects were
never diffed against `git status --short`.

## Check
Post-implementation, every `git status --short` path — code and docs
alike — must trace to a todo's Creates:/Modifies: line; a new
`__all__`/C-NNN attribute also needs an `### Added` CHANGELOG line.

## Prevention
When closing a wave, treat `git status --short`, not just files named in
the request, as scope truth: every dirty tracked path must map to a
Creates:/Modifies: line, incl. docs/skill/CHANGELOG files.
