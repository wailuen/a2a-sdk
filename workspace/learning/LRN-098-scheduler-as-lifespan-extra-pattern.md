---
id: LRN-098
title: "Scheduler-as-lifespan-extra pattern — import agent_sdk.scheduler does not exist"
category: sdk
severity: high
source: implement
date: 2026-06-20
---

## What happened

A domain agent tried to `from agent_sdk.scheduler import Scheduler` (or `import agent_sdk.scheduler`). This raised `ModuleNotFoundError` at startup. The author expected a top-level `scheduler` module analogous to other SDK utilities.

## Root cause

The Scheduler is not a standalone top-level module. It is part of `agent_sdk.contrib` and is wired in via the `lifespan_extras` mechanism. There is no `agent_sdk.scheduler` module — the import path simply does not exist.

## Check

```bash
python -c "from agent_sdk.contrib import Scheduler; print('ok')"
# Should print: ok

python -c "import agent_sdk.scheduler"
# Should raise: ModuleNotFoundError
```

## Prevention

Use the correct import path and integration pattern:
```python
from agent_sdk.contrib import Scheduler
from agent_sdk import Agent

sched = Scheduler()

@sched.cron(interval_seconds=3600)   # integer seconds, NOT a cron string
async def hourly_job():              # zero arguments — no ctx parameter
    ...

# Pass sched.lifespan (the property), NOT sched itself
agent = Agent(..., lifespan_extras=[sched.lifespan])
```

Key pitfalls:
- `cron()` takes `interval_seconds: int`, not a cron-style string like `"0 * * * *"`.
- The decorated function must take **zero arguments** — `_run_loop` calls `fn()` with no args.
- Wire `sched.lifespan` (the context-manager factory) into `lifespan_extras`, not the `Scheduler` instance.
- First run occurs **after** the first interval, not at startup. For immediate execution, call the function once before wiring up the scheduler.
- Register **all** jobs before accessing `sched.lifespan` — the property snapshots `_jobs` at access time; later registrations are ignored.

Never attempt `import agent_sdk.scheduler`. Document the `lifespan_extras` pattern in domain agent scaffolding so authors discover it before reaching for a direct import.
