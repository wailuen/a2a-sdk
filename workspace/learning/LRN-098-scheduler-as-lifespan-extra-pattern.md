---
id: LRN-098
title: "Scheduler-as-lifespan-extra pattern — import agent_sdk.scheduler does not exist"
category: sdk
severity: medium
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

scheduler = Scheduler()

@scheduler.cron("0 * * * *")
async def hourly_job(ctx):
    ...

# Register as a lifespan extra — do NOT try to import as agent_sdk.scheduler
app = build_app(..., lifespan_extras=[scheduler])
```

Never attempt `import agent_sdk.scheduler`. Document the `lifespan_extras` pattern in domain agent scaffolding so authors discover it before reaching for a direct import.
