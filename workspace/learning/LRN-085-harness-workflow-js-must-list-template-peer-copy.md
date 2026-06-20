---
id: LRN-085
title: Wave todos touching harness/workflows/*.js must list the template/.claude/workflows/ peer-repo runtime copy as a deliverable
category: ops
severity: low
source: redteam (RT-002 / w021)
date: 2026-06-19
---

## What happened
The GH-71 todo declared `Modifies: harness/workflows/acceptance-api.js` only.
The runtime copy that /acceptance actually executes is
`template/.claude/workflows/acceptance-api.js` inside `wailuen/a2a-agent-template`
(a peer git repo — see LRN-071). Propagation happened out-of-band (template repo
committed at b0aa665) so no runtime drift existed at release, but the second
deliverable was never tracked in the wave plan.

## Root cause
`harness/workflows/` is the authoring source; `template/.claude/workflows/` is the
runtime delivery copy. They are in different git repositories. A todo that lists only
the harness copy creates an implicit dependency on out-of-band propagation rather
than an explicit wave deliverable, so drift can go undetected if propagation is skipped.

## Check
After any change to `harness/workflows/<file>.js`, confirm:
```bash
diff harness/workflows/<file>.js template/.claude/workflows/<file>.js
git -C template/ log --oneline -1   # must show the propagation commit
```

## Prevention
Any wave todo that modifies `harness/workflows/*.js` MUST list
`template/.claude/workflows/<file>.js` in its `Modifies:` field with the annotation:
> (lands via commit+push to wailuen/a2a-agent-template per LRN-071;
>  runtime copy is what /acceptance / the harness skill actually executes)

The implementer must run `git -C template/ commit && git -C template/ push` as an
explicit step — never assume propagation happened implicitly.
