wave: w055
group: A1
date: 2026-10-17

Non-blocking — these did not block w055's archive. Address opportunistically or fold into a future wave.

Deduped by file + description across every unit redteam round for group A1. Where several rounds raised the
same or overlapping finding, the entries are merged into one, the strongest severity is kept, and the extra
detail from each round is folded in. The IDs below are renumbered for this note; they do not match any single
round's IDs (two rounds both used RT-002 and RT-003 for different findings). All findings are SDK-level
(sdkCandidate: true). Context: GH-190 (push notification config routes return 501 -32003).

## Findings

### RT-001
- severity: medium
- file: tests/test_gh190_push_config_not_supported.py
- description: Raised in two rounds (merged). `test_same_reply_for_existing_and_foreign_task` (line 31) has two gaps against the SI-5 acceptance condition, which names three cases: the caller's own task, a foreign task and an unknown task.
  (a) The task is built with owner `someone-else`, so the test only compares a foreign task with an unknown one. The caller's-own case is never tested, and the variable `mine` actually holds a foreign task.
  (b) The test runs through the conftest `client` fixture, which carries an ADMIN bearer (tests/conftest.py ~66-72). Admin keys skip task identity binding, so the foreign-task case is never exercised by a non-admin caller, and no test covers a non-admin caller on its own task. A later change that looks up the task for non-admin callers (and returns 404 -32001 for a foreign task) would pass this suite and reopen a way to probe whether a task exists.
- fix: Mint two non-admin keys with `app.state.auth.api_keys.mint(..., admin=False)`. Create one task owned by key A (via `store.create(new_task('ctx'), <identity A>)` or through `POST /v1/message:send` as key A). For each of the four routes, assert that key A on its own task, key B on A's task, and key B on an unknown id all return 501 with byte-identical JSON bodies. Keep the admin case as a fourth row. Rename `mine` to `foreign` where it still holds a foreign task.
- codify: A same-reply anti-enumeration test must use a non-admin caller, because the default admin test client skips identity binding and makes the foreign-task case pass trivially.

### RT-002
- severity: low
- file: agent_sdk/routes/a2a.py
- description: The route pairs are written as two stacked decorators (`@router.post` + `@router.get` at ~1054-1055, `@router.get` + `@router.delete` at ~1065-1066). That registers two separate routes on the same path. A method the path does not serve therefore gets a 405 with a wrong `Allow` header. Live probe: `PUT /v1/tasks/nope/pushNotificationConfigs` -> 405 -32004 with `allow: GET`, although POST is also served (RFC 9110 §15.5.6 says Allow lists all supported methods).
- fix: Register each path once: `@router.api_route("/v1/tasks/{task_id}/pushNotificationConfigs", methods=["GET", "POST"])` and `@router.api_route("/v1/tasks/{task_id}/pushNotificationConfigs/{config_id}", methods=["GET", "DELETE"])`. Add a test that PUT returns 405 and its Allow header names both methods.

### RT-003
- severity: low
- file: agent_sdk/routes/a2a.py
- description: The new routes `push_configs_unsupported` and `push_config_unsupported` (lines 1043-1074) cite no spec section for the paths or the -32003 code. Other protocol routes in this module cite the A2A spec. The two handler names also differ by one letter, which invites mix-ups.
- fix: In `_push_config_not_supported`, add a comment citing the A2A v0.3.0 HTTP+JSON binding for tasks/pushNotificationConfig/{set,get,list,delete} (harness/reference/a2a-protocol-0_3_0.md lines 68-69) and the PushNotificationNotSupportedError code. Rename the handlers to `push_configs_collection_unsupported` and `push_config_item_unsupported`. (If RT-002's single `api_route` registration lands first, apply the rename to the merged handlers.)

### RT-004
- severity: low
- file: docs/protocols.md, DESIGN.md
- description: Raised in two rounds (merged). The four pushNotificationConfigs routes are missing from both route lists. In docs/protocols.md the endpoint table (lines 10-17) does not list them; they appear only inside the error-table sentence (lines 21-26), which now runs on: '...body never read); unacceptable `acceptedOutputModes` → ...'. DESIGN.md §5.1 'Endpoints' lists every other /v1 route but not these four. The -32003 row ('any push-config request') still covers the behaviour, so this is drift in the route lists, not a contradiction, but readers scanning either list will think the routes do not exist.
- fix: Add a row to the docs/protocols.md endpoint table: `POST/GET /v1/tasks/{id}/pushNotificationConfigs`, `GET/DELETE …/{configId}` | 501 `-32003` (push notifications unsupported; identity required). Shorten the error-table sentence back to 'push config routes → 501 `-32003`'. Add a bullet to DESIGN.md §5.1 Endpoints: `POST`/`GET /v1/tasks/{id}/pushNotificationConfigs`, `GET`/`DELETE /v1/tasks/{id}/pushNotificationConfigs/{configId}` -> 501 `-32003`, identity required, same reply for any task id, body not read (GH-190).
