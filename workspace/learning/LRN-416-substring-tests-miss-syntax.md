---
id: LRN-416
title: Substring asserts on JS source are not a gate
category: testing
severity: high
source: redteam
date: 2026-10-17
---

## What happened
`test_chat_js_uses_policy_and_does_not_repost_after_drop` in `tests/test_gh191_console_retry_policy.py` only checks that substrings exist in chat.js. No test parses chat.js or the console module graph, so a syntax error (LRN-415) passed. It would also pass if a non-matching code path still re-POSTed after a drop.

## Root cause
Browser-side logic was tested by string presence, not by parsing or running it.

## Check
`grep -rn "node" tests/test_gh191_console_retry_policy.py` must show a `node --check` test over all `console/static/*.js`. Drop-handling logic should be tested by behaviour under node.

## Prevention
When planning console JS changes, require a node syntax gate over all static JS. Put decision logic in a pure module (e.g. `retry.js`) and test its behaviour, not its text.
