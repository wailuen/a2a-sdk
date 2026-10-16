# w053 — GitHub issues 183–184

Sourced from open issues on wailuen/a2a-sdk. Both items edit the same mint steps, so they run as one group in one todo.
Run as group:G1.
Target: 0.15.1.

---

- [ ] `GH-183` + `GH-184` Service-key mint step prints the plaintext and never checks the key is a service key ‖ group:G1
  - Creates: (modifies `harness/skills/acceptance/SKILL.md`, `harness/skills/agent-verify/SKILL.md`, `template/.claude/skills/acceptance/SKILL.md`, `template/.claude/skills/agent-verify/SKILL.md`, new `tests/test_gh183_184_service_key_mint_step.py`, `CHANGELOG.md`)
  - Reads: `agent_sdk/routes/admin.py` (`mint_key` response shape: `key_id`, `plaintext`, `service`), `harness/workflows/acceptance-api.js`, existing harness/template skill-copy tests under `tests/`
  - Severity: low
  - Root cause: GH-183: the `/acceptance` Phase 0 mint (acceptance SKILL.md, "Mint a service key (GH-182)") runs `curl -sf -X POST <base_url>/admin/api/keys ...` and lets the JSON print, so `plaintext` lands in tool output and the transcript. GH-184: neither `/acceptance` nor `/agent-verify` checks `"service": true` in the mint response; an SDK before v0.15.0 ignores the field and mints an ordinary key, so the run silently tests the wrong credential.
  - AC: In both skills, the mint is ONE command whose response never reaches stdout: it is piped to a small inline parser (python3 or jq) that (a) stops with a clear message "this SDK does not support service keys; upgrade to v0.15.0+" and a non-zero exit when `service` is not `true` (missing, false, or non-JSON response), revoking the just-minted key by `key_id` if one was returned; (b) otherwise writes `plaintext` to the key file created with mode 600 (umask 077 or chmod before writing, never after); (c) prints only `key_id`.
  - AC: The admin key is never echoed either (passed via a header read from a file or env var, as today).
  - AC: Teardown/revoke steps keep working with the printed `key_id`.
  - AC: harness and template copies stay identical except for the existing intentional workflow-path line in acceptance SKILL.md.
  - AC: A test reads both harness SKILL.md files and asserts the mint block (1) has no bare curl to `/admin/api/keys` whose output goes to stdout, (2) checks `service` is true with the upgrade message, (3) writes the key file with mode 600, (4) prints `key_id` only. The same test runs the documented parser snippet against sample responses (`service: true`, `service` absent, `service: false`) and asserts: plaintext never in stdout/stderr; failure path exits non-zero with the message.
  - AC: The template repo commit is made and pushed (tests/test_wave_scope_extraction.py::test_gh164_template_mirror_is_committed_and_pushed must pass).
  - AC: CHANGELOG `[Unreleased]` Fixed entry names both issues.
  - GH: https://github.com/wailuen/a2a-sdk/issues/183
  - GH: https://github.com/wailuen/a2a-sdk/issues/184
  - SI: SI-2  # Todo handles credentials (admin key and minted service key) but has no SI: field. Add 'SI: SI-2, SI-6'. The parser must keep plaintext out of stdout and stderr. That includes the JSON-parse error path: python3 json errors and jq errors can echo the raw input. The revoke-on-failure call must not print the plaintext either.
  - SI: SI-6  # The AC says the admin key is passed 'via a header read from a file or env var, as today'. That is false for /acceptance. harness/skills/acceptance/SKILL.md:66-67 and :604 put the literal `-H "Authorization: Bearer <admin_key>"` into the curl argv and the tool-call transcript. Fix: read the admin key from ADR-000 into a header file (curl -H @file) or an env var, for the mint, the failure-path revoke and the teardown revoke. Also, agent-verify Phase 1 step 3 (harness/skills/agent-verify/SKILL.md:58-59) mints the throwaway ADMIN key from the bootstrap token, and that response's plaintext is not covered by any AC. The GH-183 leak class applies to it too.

---

Archived 2026-10-16 by hand (the wave archive step left the file in active/). Unit redteam took 5 rounds; all highs fixed by the wave. Full suite green (3488 passed). Skill-only change: no agent_sdk code changed, so no protocol audit ran.
