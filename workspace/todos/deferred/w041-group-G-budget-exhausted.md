wave: w041
group: G
date: 2026-10-09
round_count: 5
status: budget-exhausted

## Findings

### RT-001
- severity: high
- file: workspace/todos/active/w041-gh-issues.md
- description: The RATIFY-R8 todo still says 'maintainer SIGNED OFF 2026-10-09'. Its ACs require the metadata row removed from all three advisor copies, the Profile bumped to v1.1, ROUND_8_METADATA_ROW_REMOVAL_RATIFIED = True, a SIGNED OFF Round 11 entry, and a content_types.py docstring saying the change is ratified. The landed code does the opposite: Round 11 is PROPOSED with Checkable reference PENDING, the flag derives to False, the row is kept, and the docstring says NOT applied. The todo was never updated to record this. So the archive step could mark RATIFY-R8 done with every one of its ACs unmet, and the plan and the code now disagree about whether the user approved the change. The user's /gh-review AskUserQuestion answer ('Approve removal') is the escalation channel the standing feedback rule names, so downgrading it to PROPOSED is a judgment call the user has not confirmed.
- fix: Leave RATIFY-R8 unchecked and rewrite its title, root cause and ACs to record the PROPOSED/deferred state and the reason. Escalate through AskUserQuestion: either the user confirms the /gh-review answer as sign-off and supplies a checkable reference (then apply the v1.1 edits and Round 11 flips to SIGNED OFF), or the user withdraws the entry. Do not archive w041 as complete until one of these happens.
- codify: When a wave lands a state that contradicts its todo's ACs, even for a sound governance reason, it must rewrite the todo to say so and escalate. Leaving the todo claiming sign-off lets the archive step close unmet ACs.
- sdkCandidate: true

### RT-002
- severity: medium
- file: .claude/skills/sdk-release/SKILL.md
- description: The wave added a new release-blocking rule outside this group's Creates/Modifies scope. Step 4 of sdk-release now runs SDK_RELEASE_GATE=1 against test_round8_metadata_ratification_gate.py, and that test fails today (confirmed: 1 failed). It also invented a format for the Checkable reference line: a wailuen/a2a-sdk issue/PR URL or a 40-hex SHA. As a result, the unrelated, already-landed GH-145/147/148/149/150 fixes cannot ship in 0.8.1 until a separate doc-contract decision is made. Per the standing feedback rule, new SDK policy written by a wave is only a proposal until the user ratifies it.
- fix: Ask the user to confirm the release-gate policy and the reference format. Otherwise scope the gate so it does not block unrelated fixes, for example by letting the maintainer withdraw Round 11 or mark it deferred-to-next-release. List .claude/skills/sdk-release/SKILL.md in the todo's Modifies list so the change can be traced.
- codify: A wave must not add release-blocking gates to the release skill on its own authority. A new release policy is a proposal that needs the user's ratification and must appear in the todo's Modifies scope.
- sdkCandidate: true

### RT-003
- severity: low
- file: workspace/todos/active/w041-gh-issues.md
- description: The GH-151 'UNMET / DEFERRED (RT-002)' note says test_harness_and_template_copies_are_identical[wave-cycle.js] fails. But tests/test_workflow_sync.py now passes (39 passed), so the note is stale and wrongly blocks marking GH-151 done.
- fix: Re-run .venv/bin/pytest -q tests/test_rt002_a2ui_wire_shape_mirror_parity.py tests/test_workflow_sync.py, then delete or update the UNMET note and check off GH-151. All of its ACs are met: the four template mirrors are byte-identical to harness, and the #151 carve-out and docstring note are removed.

### RT-004
- severity: low
- file: agent_sdk/models/content_types.py
- description: The module docstring (lines ~59-62) says the maintainer's sign-off 'flips ROUND_8_METADATA_ROW_REMOVAL_RATIFIED in tests/test_rt002_a2ui_wire_shape_mirror_parity.py'. That flag is no longer set by hand. It is derived from the REVIEWS.md Round 11 status line and its Checkable reference line, so the docstring points future editors to the wrong file to change.
- fix: Reword it to: 'only after REVIEWS.md Round 11 is marked SIGNED OFF with a Checkable reference (from which ROUND_8_METADATA_ROW_REMOVAL_RATIFIED is derived)'.

### RT-005
- severity: low
- file: tests/test_rt002_a2ui_wire_shape_mirror_parity.py
- description: _REFERENCE_LINE only checks the format. Any wailuen/a2a-sdk issue or PR URL passes, including #151 or the RATIFY tracking issue itself, and so does any 40-hex string, even one that is not a real commit such as 'a'*40, which test_sha_and_repo_url_references_are_accepted asserts is accepted. Once someone writes a plausible-looking line, the gate can be satisfied without real maintainer approval. Only a human reviewer stands in the way, and REVIEWS.md admits this.
- fix: For SHA references, check that `git cat-file -e <sha>^{commit}` succeeds when .git is present. Keep the human-review note. Optionally require the URL to be an issuecomment or pullrequestreview anchor rather than a bare issue.

## Instruction

Fix remaining findings, then re-run /wave w041.
