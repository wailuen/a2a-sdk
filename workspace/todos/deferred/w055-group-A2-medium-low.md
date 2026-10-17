wave: w055
group: A2
date: 2026-10-17

Non-blocking — these did not block w055's archive. Address opportunistically or fold into a future wave.

Deduped by file + description across every unit redteam round for group A2. All findings are SDK-level
(sdkCandidate: true). Context: GH-197 (A2A stream idle heartbeat `: ping` frames).

## Findings

### RT-001
- severity: medium
- file: tests/test_gh197_a2a_stream_heartbeat.py
- description: The GH-197 AC names three streams that must send heartbeats: message:stream, the interrupt-resume stream and tasks/{id}:subscribe. The test file covers only message:stream and subscribe. No test drives a taskId-bearing message:stream resume (agent_sdk/routes/a2a.py message_stream resume branch, ~line 980) while the worker is busy after the resume and checks for `: ping` frames plus the final frame. A later refactor of the resume branch that stopped going through _open_stream would ship untested.
- fix: Add a test with a tool that raises ToolInterrupt on its first call and blocks on the gate on its second. Open the resume with POST /v1/message:stream carrying the taskId while STREAM_HEARTBEAT_SECONDS is patched to 0.05. Assert at least 2 `: ping\n\n`, that the first line is the full-Task data frame, and that the last data frame has final:true.
- codify: When an AC lists several stream routes, write one heartbeat test per route, not one per shared helper.

### RT-002
- severity: medium
- file: docs/protocols.md
- description: A2A message:stream, the resume stream and tasks/{id}:subscribe now send `: ping` SSE comment frames after 15 s of idle time. This is a change clients can see on the wire. docs/protocols.md line 13 and DESIGN.md line 266 still describe the stream as only data frames: the full Task first, then status/artifact frames until final:true. Neither file mentions comment frames or the 15 s interval, for A2A or for AG-UI. The CHANGELOG is the only place that records it.
- fix: In the docs/protocols.md stream row (line 13) and DESIGN.md §5 line 266, add: 'SSE comment frames (`: ping`) are sent every agent_sdk.common.sse.STREAM_HEARTBEAT_SECONDS (15 s) while idle; clients must ignore lines that start with `:`'. Add the same note for /ag-ui/run.
- codify: A change to the bytes on a protocol stream must update docs/protocols.md and the DESIGN.md wire description, not only the CHANGELOG.

### RT-003
- severity: medium
- file: workspace/todos/active/w055-gh-issues.md
- description: GH-197 changed agent_sdk/common/sse.py (new STREAM_HEARTBEAT_SECONDS) and agent_sdk/routes/ag_ui.py (line 780 now reads the shared constant). The CHANGELOG GH-197 entry lists both files. But the todo's Creates/Modifies line lists only a2a.py, acceptance-api.js, the test, CHANGELOG and the template mirror; sse.py and ag_ui.py appear only under Reads. So this group's review scope also left out sse.py and ag_ui.py. This is the LRN-202 / LRN-059 gap: the todo's file list and the CHANGELOG file list disagree, and production edits get past the per-group review.
- fix: Add agent_sdk/common/sse.py and agent_sdk/routes/ag_ui.py (heartbeat timeout line) to GH-197's Modifies line. Make sure the wave-cycle scope for group A2 includes them in the unit and phase reviews. Also remove the stale AC text 'there is no template copy of this workflow'. The Mirror annotation and the shipped template commit both contradict it.
- codify: The files a todo declares must match the CHANGELOG entry's file list, or the redteam scope silently drops real edits.

### RT-004
- severity: low
- file: agent_sdk/routes/mcp.py
- description: agent_sdk/routes/mcp.py:142 keeps its own `_HEARTBEAT_SECONDS = 15.0` (used at lines 991 and 1117). GH-197 made agent_sdk.common.sse.STREAM_HEARTBEAT_SECONDS the shared idle-ping interval. There are now two copies of the same value, and they can drift. Tests cannot patch the MCP one through the shared constant.
- fix: Make mcp.py read `_sse.STREAM_HEARTBEAT_SECONDS` at call time, the same way a2a.py and ag_ui.py do. Then delete `_HEARTBEAT_SECONDS`. Optionally record the constant in workspace/components/README.md as the shared SSE heartbeat interval.

### RT-005
- severity: low
- file: CHANGELOG.md
- description: The GH-197 Fixed entry names harness/workflows/acceptance-api.js but not the peer-repo runtime copy template/.claude/workflows/acceptance-api.js, which the todo lists as a deliverable. The template commit that shipped it (ed451cd, already pushed) says the 600 s timeout change belongs to GH-194/GH-196, not GH-197. Anyone tracing GH-197 into the template repo will not find it.
- fix: Add the template path to the GH-197 CHANGELOG entry's Changed list. In future template sync commits, cite the GH id that owns each mirrored file. Do not rewrite the pushed commit.

### RT-006
- severity: low
- file: tests/test_gh197_a2a_stream_heartbeat.py
- description: test_disconnect_during_wait_releases_subscription checks only store._records[*].subscriptions after the disconnect. It does not check that the admission slot map (_a2a_streams(app)) is empty again. The release closure frees both, so a regression that leaked only the slot would still pass. No test covers an item queued right as the heartbeat timeout fires, which the 'queued items are never dropped' AC relies on. Today that safety comes from asyncio.Queue.get being safe to cancel, and nothing pins it.
- fix: After the disconnect, also assert `not _a2a_streams(hb_app)`, imported from agent_sdk.routes.a2a. Add a small unit test that publishes a frame from a callback scheduled just before a 0-0.01 s heartbeat timeout, over many runs. Assert every published frame appears in the stream exactly once and in order.
