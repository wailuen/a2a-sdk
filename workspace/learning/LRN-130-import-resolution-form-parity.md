---
id: LRN-130
title: Relative direct-module import form skipped submodule check, false-positive-blocked archive
category: ops
severity: high
source: redteam
date: 2026-07-20
---

## What happened
sdk-wave.js step 5b's RELATIVE `from <dots><path> import <name>` branch
resolved straight to `<path>.py`, skipping the submodule check the
ABSOLUTE form had. `from ..credentials import forwarding` (routes/a2a.py,
mcp.py, ag_ui.py) mis-resolved to nonexistent `agent_sdk/credentials.py`;
offender logic lacked an existence check, so it false-positive-blocked
archive.

## Root cause
A new import-form branch skipped the sibling forms' submodule
disambiguation ladder; offender detection lacked an existence check.

## Check
grep sdk-wave.js for "NEVER to the nonexistent" near the RELATIVE
from-import-with-path branch; confirm it mirrors the ABSOLUTE form's
submodule -> sub-package -> pkg-as-module ladder, and step 5c requires
the resolved path to EXIST on disk before flagging
offendingUndeclaredImports. Add a test_workflows.py case for
`from ..credentials import forwarding`.

## Prevention
When planning an import-resolution gate with multiple form branches,
require every branch use the identical on-disk disambiguation ladder,
and require offender verdicts to require the resolved path exist.
