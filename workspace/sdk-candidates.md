# SDK issue candidates — w053 (2026-10-16)

Run `/sdk-issue-scan` to review and file as GitHub issues on `wailuen/a2a-sdk`.

## Candidate 1: RT-001: acceptance SKILL.md still deletes the service key file (unlinkSync) right after the first Workflow call. The key now lives only in that file, so every later fix-loop re-run and Phase 2B reads a deleted file and fails. Fix: remove the unlink after Workflow(); delete the file only in the 'Service key teardown' section next to the revoke; update the acceptance-api.js header comment; add a test.
- Severity: high
- Component: harness/skill
- File: harness/skills/acceptance/SKILL.md
- Rationale: Harness skill shipped to every agent repo (also in template/ and .claude/ copies). It breaks the /acceptance fix loop. This is not agent domain code.

## Candidate 2: RT-002: The acceptance 'Service key teardown' revoke still runs curl with 'Authorization: Bearer <admin_key>' on the command line. That puts the admin key in the command arguments and the transcript, against the SI-6 header-from-file rule. Fix: pipe the header through stdin (-H @-), load ADMIN_KEY in the same command, then rm -f the key file. Add a test that no copy contains 'Bearer <admin_key>'.
- Severity: high
- Component: security
- File: harness/skills/acceptance/SKILL.md
- Rationale: A secret leaks into the transcript from a harness skill that every agent repo uses. It is a security issue in SDK-owned harness content.

## Candidate 3: RT-003: The service key mint block in acceptance (and agent-verify step 4) needs BASE_URL, ADMIN_KEY, SERVICE_KEY_FILE and KEY_LABEL exported, but gives no command to set them. Each Bash call starts a fresh shell. So the agent either writes the admin key inline (leak), or uses unexported variables and python raises KeyError after the key is minted, leaving it neither stored nor revoked. Fix: make the block self-contained with exports and an ADMIN_KEY loader from the ADR-000 file in the same command; add tests with unexported variables.
- Severity: high
- Component: harness/skill
- File: harness/skills/acceptance/SKILL.md
- Rationale: Harness skill instructions that cannot be followed safely. It causes either a secret leak or an orphaned key. It affects both the acceptance and agent-verify harness skills.

## Candidate 4: RT-004: agent-verify Phase 1 step 3 (mint a throwaway admin key from the bootstrap token) gives no command and no output handling, so the admin key plaintext prints to the transcript (GH-183 leak class). Step 4 says to read ADMIN_KEY 'from the credentials file', but agent-verify has no such file. Fix: one command that pipes the bootstrap header via -H @- into a parser, writes the plaintext to a mode-600 ADMIN_KEY_FILE and prints only key_id; load it in step 4; extend the tests.
- Severity: high
- Component: security
- File: harness/skills/agent-verify/SKILL.md
- Rationale: The admin credential leaks through a harness skill shipped to all agent repos. This is an SDK security issue.

## Candidate 5: RT-001 (agent-verify): The step-3 bootstrap token awk 'f&&NF{print $1;exit}' takes the first word of the first non-empty line after the banner header. The real banner from agent_sdk/auth/api_keys.py has 'Bootstrap token (valid 15 min, single use):' there, so it sends 'X-Bootstrap-Token: Bootstrap'. The server answers 401 and every authenticated agent-verify step after it fails. The test passes only because of a hand-written fixture. Fix: match the indented token line, mirror to template/ and .claude/, and build the test fixture from BootstrapManager.arm_if_needed() output.
- Severity: high
- Component: harness/skill
- File: harness/skills/agent-verify/SKILL.md
- Rationale: A harness skill (already pushed to template 53a532a) is broken against the SDK's own bootstrap banner. It breaks /agent-verify in every agent repo.

## Candidate 6: RT-001 (acceptance Phase 0): The service key is written to /tmp/acc-key-<run-id>.txt, but <run-id> is only defined later and is guessable (run-001) and shared across repos. Two runs at once overwrite or delete each other's key. On a shared /tmp another user can create the file first with mode 666; chmod 600 fails silently and the key lands in a file they can read. Fix: use mktemp in the same command and print the path; open with O_NOFOLLOW and check owner uid and mode 0o600 with fstat; fail closed; add a test.
- Severity: high
- Component: security
- File: harness/skills/acceptance/SKILL.md
- Rationale: Insecure temp file handling of a secret in a harness skill. It is a step back from the earlier random path. This is an SDK security issue.

## Candidate 7: RT-001 (template): template/.claude/skills/acceptance/SKILL.md was copied whole from harness and is now byte-identical. This wipes out the one intended difference: the live scriptPath now points at harness/workflows/acceptance-api.js, which does not exist in agent repos (they use .claude/workflows/). The file is also uncommitted in the template repo. Fix: restore the .claude/workflows/acceptance-api.js scriptPath, keep every other line identical, commit and push the template repo, and confirm the status is clean and nothing is left unpushed.
- Severity: high
- Component: harness/template
- File: template/.claude/skills/acceptance/SKILL.md
- Rationale: Template scaffold drift. Publishing it as-is breaks /acceptance in every agent repo, and the security hardening is not yet published.

## Candidate 8: RT-002 (test guard): tests/test_gh183_184_service_key_mint_step.py::test_skill_copies_use_same_block calls pytest.skip when the template copy is missing (silent-skip pattern, LRN-325) and compares only the mint block. No test pins the template acceptance scriptPath to .claude/workflows/, and none checks that the template skill copies are committed and pushed. As a result, the template drift passes all 181 related tests. Fix: fail instead of skipping; add a whole-file harness-vs-template diff with an allow-list for the scriptPath line; extend the pushed-mirror test to cover the skills directories.
- Severity: high
- Component: harness/template
- File: tests/test_gh183_184_service_key_mint_step.py
- Rationale: An SDK test-suite gap. The mirror guard for harness and template skill copies cannot catch whole-file drift or unpushed template changes.
