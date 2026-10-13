---
id: LRN-328
title: Content-type allowlist skips non-list payload shapes
category: protocol
severity: high
source: redteam
date: 2026-10-13
---

## What happened
GH-159 rejects non-text parts in AG-UI user messages. `_validate` in `agent_sdk/routes/ag_ui.py` skipped any content that was not a list. A dict-shaped binary content passed, and `_fold_history` ran `str(content)` and sent the base64 data to the model as text.

## Root cause
The allowlist only checked the expected list shape. Other shapes fell through to a lenient `str()` step.

## Check
Run a test in `tests/test_gh159_reject_non_text_parts.py` that sends `{"role":"user","content":{"type":"binary","data":"..."}}`, expects RUN_ERROR, and asserts no task is created. Also grep `ag_ui.py` for `not isinstance(content, list): continue` and confirm no match.

## Prevention
When planning payload validation, ensure user content accepts only `str` or `list` (a dict is normalized to a one-element list or rejected). Test every shape the payload can arrive in, not just the list shape.
