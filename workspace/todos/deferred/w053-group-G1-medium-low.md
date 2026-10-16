wave: w053
group: G1
date: 2026-10-16

Non-blocking — these did not block w053's archive. Address opportunistically or fold into a future wave.

Deduped by file + description across every unit redteam round for group G1. Where several rounds raised the
same finding, the entries are merged into one, the strongest severity is kept, and the extra detail from each
round is folded in. The IDs below are renumbered for this note; they do not match any single round's IDs.
All findings are SDK-level (sdkCandidate: true unless noted). Context: GH-183/GH-184 (service-key mint step in
/acceptance and /agent-verify prints only key_id + key-file path; plaintext and admin key never echoed).
Every skill fix must be mirrored to harness/skills/, .claude/skills/ and the template copy.

## Findings

### RT-001
- severity: medium
- file: harness/skills/acceptance/SKILL.md (also harness/skills/agent-verify/SKILL.md)
- description: Raised in all five rounds. Both mint parsers (acceptance ~lines 83-105, agent-verify ~96-117) print "this SDK does not support service keys; upgrade to v0.15.0+" for every non-success outcome. curl runs with `-s` and no `-f`, so this covers: a 401 `{"detail":...}` from a wrong or stale admin key; an empty ADMIN_KEY when the ADR-000 regex `^admin_key:\s*(\S+)` misses (quoted or indented value) — the mint is still sent with `Bearer `; an empty ADMIN_KEY_FILE in agent-verify after a failed step 3; a 403; a 5xx; and connection refused (empty stdin, non-JSON). In /acceptance the mint is Phase 0 step 2, which runs BEFORE step 3 "Confirm server is alive". A v0.15.0+ server that is down or misconfigured therefore tells the operator to upgrade an SDK that is already current, hiding the real cause.
- fix: (1) Stop before curl when ADMIN_KEY is empty ("admin_key not found in ADR-000"). (2) Move the liveness check before the mint. (3) Capture the HTTP status without echoing the body (e.g. `curl -s -w '\n%{http_code}'`, split the last line in python). Show the upgrade message only when a 2xx dict with a string key_id/plaintext came back and `service` is not True (or a 422 for an unknown `service` field); revoke in that case. Otherwise exit non-zero with "service key mint failed: HTTP <code> (check admin key / server)" — status code or `detail` only, never the raw body. If the AC string must be kept literally, keep it and add the second reason line. (4) Add tests for a 401 JSON body and an empty response.
- codify: A version-gate error message should fire only on the version signal, not on every failure. Auth and transport failures need their own message or they send operators to the wrong fix.

### RT-002
- severity: medium
- file: harness/skills/agent-verify/SKILL.md
- description: Raised in four rounds. The agent-verify key-file writes (step 3 throwaway admin key, ~lines 65-80; step 4 service key, ~92-117) use an unspecified `<throwaway ... path>` placeholder, then `: > "$FILE"; chmod 600` and `os.open(O_WRONLY|O_CREAT|O_TRUNC, 0o600)`. No mktemp, no O_NOFOLLOW, no owner/mode check. If the model picks a predictable /tmp path that another local user already holds (symlink, or a file with mode 0666), `:>` and os.open follow the symlink, `chmod 600` fails silently (joined with `;`, no `set -e`), and 0o600 is ignored for an existing file — so the admin or service key lands in a file another user can read (SI-2). /acceptance was hardened against exactly this during w053 (earlier rounds flagged its predictable `/tmp/acc-key-<run-id>.txt` path, where `<run-id>` is undefined at Phase 0, as a regression from `randomUUID()`), so the two skills now protect the same secret differently, breaking AC (b) "key file created with mode 600".
- fix: Use the /acceptance pattern for both agent-verify keys: `export ADMIN_KEY_FILE="$(mktemp "${TMPDIR:-/tmp}/av-admin-XXXXXX")"` (same for SERVICE_KEY_FILE), drop `: >` and chmod, open with `os.O_WRONLY|os.O_TRUNC|os.O_NOFOLLOW` (no O_CREAT), and refuse to write unless fstat shows st_uid == getuid() and mode 0o600. Print the path (not secret). Add a test like test_acceptance_mint_refuses_foreign_mode_file for agent-verify. Re-confirm the acceptance block still has all of these.
- codify: Every skill block that writes a credential to disk must use mktemp plus O_NOFOLLOW plus an owner/mode fstat check. Hardening one skill's copy and not its sibling leaves the same secret exposed.

### RT-003
- severity: medium
- file: harness/skills/agent-verify/SKILL.md
- description: Raised in four rounds. Phase 5 teardown (~lines 180-185, step 7) is prose only: "revoke the service key (DELETE /admin/api/keys/<key_id> with the admin key) ... remove any throwaway key/data dir". No ready command, so the model builds its own and will likely put the admin key in curl argv or cat it into the transcript — the leak class GH-183 closed for the mint, and against the SI-6 annotation requiring header-from-file/stdin. The throwaway admin key minted from the bootstrap token in step 3 is never named and never revoked. ADMIN_KEY_FILE/SERVICE_KEY_FILE removal is only implied. The AC "teardown/revoke steps keep working with the printed key_id" has no codified, tested step in agent-verify (acceptance has test_acceptance_teardown_revokes_without_argv_key).
- fix: Name the step-3 output `<admin_key_id>`. Add a bash teardown block mirroring /acceptance: `export ADMIN_KEY="$(cat "$ADMIN_KEY_FILE")"`; `printf 'Authorization: Bearer %s\n' "$ADMIN_KEY" | curl -s -o /dev/null -w '%{http_code}\n' -X DELETE "$BASE_URL/admin/api/keys/$SERVICE_KEY_ID" -H @-`; then the same for the admin key id; then `rm -f "$SERVICE_KEY_FILE" "$ADMIN_KEY_FILE"`. Extend the GH-183/184 test to run that block against the fake curl.
- codify: Every credential revoke step in a skill must be a concrete stdin-header command with a test. Prose like "DELETE with the admin key" invites argv and transcript exposure.

### RT-004
- severity: medium
- file: harness/skills/acceptance/SKILL.md
- description: Raised in two rounds. Phase 0 step 2 (~lines 56-59) still says "Open workspace/adr/ADR-000-<env>-credentials.md. Parse the YAML frontmatter: extract endpoint ... and admin_key". Followed with the Read tool, this puts the admin key straight into the transcript, defeating the mint/teardown blocks that load ADMIN_KEY themselves, and breaking the todo AC "The admin key is never echoed either" and the SI-6 note.
- fix: Rewrite step 2 to extract only `endpoint` (e.g. `grep '^endpoint:'`) and confirm admin_key exists without showing it (`grep -c '^admin_key:'` or a python one-liner printing present/missing). State explicitly: never open ADR-000 with Read or cat. Add a static test that step 2 does not tell the model to extract admin_key.
- codify: When a skill moves a secret into self-loading shell blocks, every earlier step that tells the model to read that secret must be removed too, or the transcript leak comes back.

### RT-005
- severity: medium
- file: harness/skills/agent-verify/SKILL.md
- description: Raised in two rounds. The Phase 1 step 3 bootstrap-token extractor (~line 67) uses the awk interval expression `[A-Za-z0-9_-]{20,}`. mawk (e.g. 1.3.4-20200120, default awk on Ubuntu 22.04 / Debian 11–12) may not support `{n,}` intervals (plausible, not verified here). There the pattern never matches, no X-Bootstrap-Token header is sent, the server answers 401, and /agent-verify always stops with "admin key mint failed" on those Linux hosts. The test only runs on macOS BWK awk 20200816, so it passes.
- fix: Extract the token in python3 (already required by the block), e.g. `re.search(r"=== agent-sdk first-run bootstrap ===.*?\n\s+([A-Za-z0-9_-]{20,})\s*\n", t, re.S)` and print only the header line; or use an interval-free check `f && NF==1 && length($1)>=20 && $1 ~ /^[A-Za-z0-9_-]+$/`; or grep -E. Add a test asserting the block uses no awk interval syntax; run under mawk/busybox in CI if available.

### RT-006
- severity: medium
- file: harness/skills/acceptance/SKILL.md (also harness/skills/agent-verify/SKILL.md)
- description: Raised in five rounds. Failure-path cleanup gaps in both mint parsers. (a) The revoke-on-failure call (`subprocess.run([... '-s', '-o', '/dev/null' ...], check=False)`, acceptance ~92-96, agent-verify ~108-112) discards its result; if the DELETE fails (non-200, timeout, reset), an ordinary non-service key stays live and its key_id is never printed, so the operator cannot revoke it by hand. (b) When `service` is true but the key-file write fails ("service key file is not private", O_NOFOLLOW/ELOOP OSError) or `key_id` is missing (KeyError — the file is written before `print(d["key_id"])`), the freshly minted live service key is never revoked and its id is lost, so teardown cannot find it. (c) The empty mktemp key file is left behind on any failure.
- fix: Add `isinstance(d.get("key_id"), str)` to the success condition. Wrap the write in try/except; on any failure after a mint, revoke by key_id via the same stdin-header subprocess. Capture the revoke status with `-w '%{http_code}'` and `capture_output=True`; if not 200, write "could not revoke key <key_id> (HTTP <code>); revoke it manually in /admin" to stderr (key_id is not secret). `os.remove(SERVICE_KEY_FILE)` on every failure path. Add tests: fake DELETE returns 500 / exits non-zero (key_id reported, plaintext never printed); 2xx with service:true but no key_id.
- codify: A best-effort revoke of a stray credential must check its own result and report the key id on failure. A silent check=False leaves a live, untracked key.

### RT-007
- severity: low
- file: harness/skills/acceptance/SKILL.md (also harness/workflows/acceptance-api.js)
- description: Raised in five rounds (LRN-392 class: stale text after the switch to a file-only key). (a) The `<service_key>` placeholder is still used in `Authorization: Bearer <service_key>` (~lines 194/198, 202/206, 262/266, 268/272) but is no longer defined — Phase 0 defines only <service_key_id> and <service_key_file> — so an agent filling it must read the key into the transcript. (b) Rules > "No secrets in output" (~line 658-663) says the key is written to "/tmp/acc-key-<random>.txt" "by the workflow before sub-agents are spawned"; it is now written by the Phase 0 mint. (c) The Workflow invocation comment (~lines 307-313) still says "the key file must be written HERE (in the skill caller context) before Workflow() is invoked", contradicting "do not rewrite it". harness/workflows/acceptance-api.js:13 and 301-308 still say the caller writes and unlinks it. (d) `const _keyFile = <service_key_file>` is unquoted, so literal substitution is a JS syntax error. (e) ~line 331 says Phase 2B reuses the key file, but Phase 2B drives /admin through Playwright and never reads it.
- fix: Replace `<service_key>` with "Bearer token = contents of <service_key_file>, read in code by the workflow sub-agent, never printed". Rewrite the Rules bullet, the invocation comment and the acceptance-api.js contract comment to say: created by the Phase 0 mint (mode 600), reused unchanged by every Workflow call, removed only at the "Service key teardown" step. Write `const _keyFile = '<service_key_file>'`. Drop the Phase 2B claim. Grep the skill, acceptance-api.js and every mirrored copy for `<service_key>`.

### RT-008
- severity: low
- file: CHANGELOG.md
- description: Raised in three rounds (LRN-267/LRN-379 class). The [Unreleased] Fixed entry describes only the parser and says the step "prints only key_id" (acceptance also prints the file path). It omits behaviour changes: (1) the acceptance key file is no longer unlinked after each Workflow() run — it is reused across Phase 3 re-runs and lives until teardown (acceptance-api.js contract comment changed); (2) the agent-verify bootstrap admin-key mint was rewritten as a piped command; (3) the teardown revoke now sends the header via stdin. The changed tests/test_rt004_r5_acceptance_skill_mirror_parity.py is not named.
- fix: Extend the bullet: key_id + file path printed; name acceptance-api.js and the key-file lifecycle change; the agent-verify bootstrap mint rewrite; the header-via-stdin teardown; the updated rt004 test.

### RT-009
- severity: low
- file: tests/test_gh183_184_service_key_mint_step.py
- description: Raised in four rounds. (a) In test_mint_block_static_shape (~line 51), `assert "-o" not in block.split("python3")[0]` checks nothing for /acceptance: the first `python3` is the `export ADMIN_KEY="$(python3 ...` loader before the curl, so the curl command is never inspected and AC (1) "no curl to /admin/api/keys whose output goes to stdout/elsewhere" is not enforced. (b) Only the single block containing `"service\":true` is checked; other /admin/api/keys bash blocks in either skill are never checked. (c) `_MemStore` (~line 185) is a hand-rolled CredentialStore double and the test reads private `mgr._token`; the harness no-mock rule asks for real stores.
- fix: Isolate each curl directly, e.g. `re.search(r"curl [^|]*?/admin/api/keys[^|]*", block, re.S)`, and assert no `-o`/`--output`/`>` in that slice and that the pipe target is the parser. Run the check over every bash block containing /admin/api/keys: each curl must pipe into python3 or carry `-o /dev/null`. Build ApiKeyStore on `EncryptedSqliteStore(tmp_path/...)` and parse the token from the printed banner instead of `_token`.

### RT-010
- severity: low
- file: tests/test_rt004_r5_acceptance_skill_mirror_parity.py
- description: test_neither_half_interpolates_the_resolved_admin_key still asserts `"mode: 0o600" in text`. After this change the only match in the acceptance SKILL.md is a JS comment (~line 311, "created by the Phase 0 mint step with { mode: 0o600 }"). Deleting the real mode-600 logic would still pass.
- fix: Assert against the mint bash block instead (`umask 077` / `0o600` in the os.open call, or the mktemp + fstat mode check), or drop the assertion since test_gh183_184 covers mode 600.

### RT-011
- severity: low
- file: harness/skills/acceptance/SKILL.md (also harness/skills/agent-verify/SKILL.md)
- description: The mint body is built as `-d "{\"label\":\"$KEY_LABEL\",\"service\":true}"`. KEY_LABEL is not JSON-escaped, so a label containing a quote or backslash produces invalid JSON (a 422, then misreported as "upgrade" — see RT-001) or injects fields such as `"admin":true`. The server rejects admin+service, but the body is still under operator-string control.
- fix: Build the body with python3 (`json.dumps({'label': os.environ['KEY_LABEL'], 'service': True})`) or `jq -n --arg l "$KEY_LABEL"` and pipe via `-d @-`, or restrict KEY_LABEL to `[A-Za-z0-9_-]`.
