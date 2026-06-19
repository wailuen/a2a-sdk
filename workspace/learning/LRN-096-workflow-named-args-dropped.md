---
id: LRN-096
title: "Workflow({name, args}) drops args — named-workflow resolver has undefined args global"
category: ops
severity: high
source: implement
date: 2026-06-20
---

## What happened

A wave step invoked a named workflow via `Workflow({ name: "some-workflow", args: { ... } })`. The workflow ran but received no arguments — all `args` values were `undefined` inside the script body, causing the step to behave as if called with defaults/empty args.

## Root cause

The Claude Code named-workflow resolver has a bug: the `args` global is `undefined` inside named scripts invoked through the `{ name, args }` form. The resolver dispatches to the script by name but does not inject the caller's `args` into the execution context, so the script sees an empty or undefined `args` binding.

## Check

If a named workflow step depends on caller-supplied args, verify the args are actually received:
```js
// Inside the workflow script — if this prints undefined, you hit the bug
console.log("args:", JSON.stringify(args));
```
Or inspect step output for silent defaults that should have been overridden.

## Prevention

Use the `scriptPath` invocation form instead of the `{ name, args }` form when args must be forwarded:
```js
// Safe — args are reliably injected when using scriptPath
Workflow({ scriptPath: ".claude/workflows/some-workflow.js", args: { key: "value" } })
```
Never rely on the named-workflow `args` forwarding until the upstream Claude Code bug is resolved.
