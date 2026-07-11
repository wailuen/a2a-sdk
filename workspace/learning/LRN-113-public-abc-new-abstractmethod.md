---
id: LRN-113
title: New abstractmethod on public ABC breaks external subclasses
category: sdk
severity: high
source: redteam
date: 2026-07-11
---

## What happened
AGUI-1's clock-agnostic interrupt-TTL fix added `interrupt_ttl_remaining` to
`TaskStore` (agent_sdk/tasks/store.py) as `@abc.abstractmethod`. `TaskStore`
is a documented extension point (docs/deployment.md `Agent(task_store=...)`,
DESIGN.md), so every external subclass predating the hook would raise
`TypeError` at instantiation on upgrade — a hard break shipped in a patch.

## Root cause
A new store hook was added as `@abc.abstractmethod` instead of a concrete
method with a safe default, treating a user-subclassable ABC as if only
internal subclasses existed.

## Check
`grep -B1 'def interrupt_ttl_remaining' agent_sdk/tasks/store.py` must NOT
show `@abc.abstractmethod` on the preceding line, and the method must return
`None` by default. Generalize: before any release, diff `@abc.abstractmethod`
decorators in agent_sdk/tasks/store.py (and other ABCs referenced in
docs/deployment.md or DESIGN.md as extension points) against the prior
release tag — any new one requires a minor/major bump + CHANGELOG breaking
note, never a silent patch.

## Prevention
When planning new hooks on any public ABC that's a documented extension
point, add them as concrete methods with a safe/no-op default (matching
existing caller null-handling) rather than `@abc.abstractmethod`, unless the
plan explicitly calls for a version bump and CHANGELOG breaking-change entry.
