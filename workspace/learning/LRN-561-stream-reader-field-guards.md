---
id: LRN-561
title: Stream reader shape guard misses dereferenced fields
category: testing
severity: high
source: redteam
date: 2026-10-25
---

## What happened
ChatDriver._run_agui guarded the frame and delta shapes, but three AG-UI frames still crashed with a traceback: CUSTOM AGENT_ARTIFACT with a str value (AttributeError), RUN_FINISHED with dict interrupts (KeyError 0), RUN_ERROR with an int message (TypeError in join). CHANGELOG claimed no exception escapes run_turn.

## Root cause
The guard checked container types only; fields later dereferenced (.get, [0], " ".join) were never type-checked.

## Check
Run tests/test_gh237_testing_clients.py cases for AGENT_ARTIFACT non-dict value, non-list interrupts and non-str RUN_ERROR message; each must give reason == "malformed-stream" with no exception. grep chat.py for `isinstance` near `_fire(emit, "artifact"`.

## Prevention
When planning a stream reader, list every field the loop dereferences and require a type guard plus a wrong-typed probe test for each, routed to the malformed-stream path.
