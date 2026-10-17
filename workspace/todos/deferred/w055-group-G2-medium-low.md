wave: w055
group: G2
date: 2026-10-17

Non-blocking — these did not block w055's archive. Address opportunistically or fold into a future wave.

Deduped by file + description across every unit redteam round for group G2. Where several rounds raised the
same finding, the entries are merged into one, the strongest severity is kept, and the extra detail from each
round is folded in. The IDs below are renumbered for this note; they do not match any single round's IDs.
All findings are SDK-level (sdkCandidate: true). Context: GH-188 (catalogs from emits), GH-194 (empty-reply
retry), GH-196 (reject unknown tool args).

## Findings

### RT-001
- severity: medium
- file: agent_sdk/agent/registry.py
- description: Raised in three rounds. `_declared_argument_keys` (~line 331-374) accepts keys that pydantic's `model_validate` then silently ignores, which is the exact GH-196 failure (a filter that seems applied but is not). Three shapes, all verified: (a) the Python field name is always allowed, even when the field has an alias and the model does not accept names (no populate_by_name / validate_by_name). With `region: str | None = Field(None, alias="regionCode")`, invoke({'ticker':'A','region':'EU'}) passes and returns region=None; input_schema() advertises only 'regionCode'. (b) When a field has both `alias` and `validation_alias`, pydantic validates only by `validation_alias`, but `alias` is still added. With `sector: str | None = Field(None, alias="a", validation_alias="b")`, invoke({"a": "TECH"}) returns ok with sector=None while the schema says additionalProperties:false (pydantic 2.13.4). (c) When the model sets validate_by_alias=False (pydantic 2.11+), aliases are still added though pydantic ignores them.
- fix: Build the accepted-key set to match what pydantic accepts. Add the field name only when there is no alias/validation_alias, or when model_config populate_by_name / validate_by_name is True. Add `finfo.alias` only when `finfo.validation_alias is None`. Add alias/validation_alias keys only when `model_config.get("validate_by_alias", True)`. Add parametrized tests in tests/test_gh196_reject_unknown_tool_args.py: alias-only field rejects the snake_case key; alias+validation_alias rejects `alias` and accepts `validation_alias`; validate_by_alias=False with validate_by_name=True; populate_by_name=True lets both through (already covered).
- codify: The accepted-key set for an unknown-argument check must match what pydantic's model_validate actually accepts (validation_alias wins over alias; validate_by_alias=False turns aliases off; field names need populate_by_name when aliased), or keys are still silently dropped.

### RT-002
- severity: medium
- file: agent_sdk/agent/registry.py (also agent_sdk/agent/loop.py safe_validation_message / _redact_loc)
- description: Raised in four rounds. `_check_unknown_arguments` returns early when model_config extra == "forbid" (~line 367-398). Pydantic's own extra_forbidden then fires, and `_redact_loc` / safe_validation_message render the key as '<extra> — unexpected field'. So for forbid models the model is not told which key to fix, which breaks the GH-196 AC "the error the model sees names the unknown key(s)", and the same mistake gets different error text depending on model config. The safe_validation_message docstring (loop.py ~1159) still says extra field names are always redacted, which is no longer true.
- fix: Return early only for extra == "allow". Let forbid models go through the same unknown-key check so they get the same `unknown_argument` error that names the key, before model_validate. Update the safe_validation_message and _redact_loc docstrings to describe the GH-196 exception. Add a test with an extra="forbid" model asserting the key name is in the loop error and the value is not.

### RT-003
- severity: medium
- file: agent_sdk/agent/loop.py
- description: Raised in two rounds. `_empty_reply_retry` (~line 536) builds its request with `_summary_request_messages`, which adds `_FINAL_SUMMARY_INSTRUCTION` ('You have reached the limit for this task and can call no more tools ... Say clearly what is still missing or uncertain'). On the GH-194 path no limit was reached and the tools succeeded, so the model gets a false premise. It is pushed to tell the user it hit a step or budget limit, or to frame a complete answer as cut short, and the user sees that as the final reply. No test checks what instruction the retry sends.
- fix: Give `_summary_request_messages` an instruction parameter (or add a sibling helper) and pass a new fixed constant for the empty-reply case, e.g. 'Write your reply to the user using the tool results above. Do not call any tools.' Keep the real transcript untouched. Add a test that model.calls[-1]'s last user block carries the empty-reply text and not the limit text.

### RT-004
- severity: medium
- file: agent_sdk/app.py (also agent_sdk/config.py, docs/tools.md)
- description: Raised in two rounds. `LoopPolicies.empty_reply_retry` cannot be turned off by any agent built with `Agent.build_app()`. app.py:643-650 builds LoopPolicies from settings and passes only max_turns/deadline/token_budget/max_output_tokens/final_summary/final_summary_max_tokens; there is no BaseAgentSettings field or env var for the new flag and build_app takes no policies override. The GH-194 AC "empty_reply_retry=False restores today's behaviour" works only for direct run_loop callers, or by mutating app.state.loop_policies after boot (undocumented). docs/tools.md:144-151 says "Set False" and that policies are tuned "via BaseAgentSettings or LoopPolicies"; neither works for a deployed agent. The GH-155 precedent (final_summary) has both a settings field (AGENT_SDK_FINAL_SUMMARY) and app.py plumbing.
- fix: Add `empty_reply_retry: bool = Field(default=True, alias="AGENT_SDK_EMPTY_REPLY_RETRY")` to BaseAgentSettings next to final_summary, pass `empty_reply_retry=settings.empty_reply_retry` in the LoopPolicies(...) call at app.py:643, document the env var in docs/tools.md and the CHANGELOG GH-194 entry, and add a test that builds the app with the env var set to false and checks app.state.loop_policies.empty_reply_retry is False.
- codify: A new LoopPolicies field needs a matching BaseAgentSettings field and app.py plumbing, or deployed agents can never change it.

### RT-005
- severity: medium
- file: agent_sdk/agent/registry.py (also agent_sdk/agent/loop.py, agent_sdk/a2ui/catalog.py)
- description: Raised in four rounds. The C-010 reuse note asked for ONE private helper holding both the unknown-key check and model_validate (e.g. `ToolEntry._validate_input`), called by invoke() and invoke_gen() ("Do not add the check twice"). The landed code shares only `_check_unknown_arguments`, which is still called at two sites (~809 and ~855), and the narrow `try: model_validate / except ValidationError -> ToolInputValidationError` block is still copied in both methods (~810-818 and ~853-861), so the paths can drift (LRN-236/LRN-287 pattern). Also: loop.py ~1174 hard-codes 'unknown_argument' instead of importing registry.UNKNOWN_ARGUMENT_ERROR_TYPE, so renaming the constant would quietly send these errors back through _redact_loc; and the a2ui_extension() docstring does not mention the new emits parameter.
- fix: Add `ToolEntry._validate_input(self, arguments) -> BaseModel | None` that runs `_check_unknown_arguments` and the narrow model_validate try (keep the RT-004 comment), raising ToolInputValidationError. Call it from both invoke() and invoke_gen() and delete the inline copies. Import UNKNOWN_ARGUMENT_ERROR_TYPE in loop.py. Document emits in the a2ui_extension docstring.

### RT-006
- severity: medium
- file: agent_sdk/agent/registry.py (also docs/tools.md, harness/skills/add-tool/SKILL.md, CHANGELOG.md)
- description: The GH-196 check only looks at top-level keys. Unknown keys inside nested BaseModel fields are still dropped silently. Verified live: `filters: Nested` where Nested has `sector: str | None`, called with {"filters":{"sectr":"TECH"}}, gives filters.sector=None and an unfiltered result that looks filtered. Neither docs/tools.md nor the CHANGELOG Breaking entry says nested objects are not covered.
- fix: Either walk nested BaseModel field values with the same declared-key rule, or state the top-level-only scope in docs/tools.md, harness/skills/add-tool/SKILL.md (plus the template mirror) and the CHANGELOG entry, and recommend extra="forbid" on nested models.

### RT-007
- severity: medium
- file: agent_sdk/agent/registry.py (also contrib commitments store.py/executor.py, CHANGELOG.md)
- description: GH-196 makes stored and sample argument dicts fail at run time, with no warning and no migration note. (1) The `sample=` dict on `@tools.tool` (powers the console Try button) is never checked against the input model at registration (registry.py ~398/459/634), so a sample with a stale key now fails Try after upgrade. (2) `contrib.commitments` `store.add()` (store.py:160) does not check args against the tool, so a commitment scheduled before the upgrade, or with an extra key, fails only when it fires, possibly days later (executor.py:153 marks it failed). The CHANGELOG migration steps mention neither case.
- fix: At registration, when `sample` is set and the tool does not opt out, run the same unknown-key check over `sample` and raise ValueError (fail at boot, not on click). Add a migration line to the GH-196 Breaking entry: check `sample=` dicts and any pending commitments for keys the input model does not declare.

### RT-008
- severity: medium
- file: tests/test_gh188_catalogs_from_emits.py (also tests/test_card_console.py)
- description: Raised in four rounds. The GH-188 ACs ('an agent whose only emitting tool emits a domain card advertises only that domain catalog', 'unemitted registered catalog not advertised', 'Profile emitter lists Standard first') are tested only by calling supported_catalogs() directly. Only an empty registry goes through build_agent_card, so the agent_card.py:172-175 wiring (`[e.decl.emits for e in registry.all() if e.decl.emits is not None]`, including tier-2 emitters and the a2ui_allowed_components pass-through) is never checked with real tools; a regression there would pass every test except the empty-registry one. The SC-D2 tests in tests/test_a2ui_group_d.py cover only the legacy emits=None fallback. Separately, both the GH-188 ruling and the todo's Modifies list name tests/test_card_console.py, but it is unchanged: test_card_shape (~line 36) still asserts only that `urn:a2ui-profile:standard:v1` is in supportedCatalogIds, which passes under the old "list every catalog" rule too.
- fix: Add build_agent_card tests using a real ToolRegistry/ToolSet: (a) one tool emits _Gh188Card, giving supportedCatalogIds == ['urn:test-gh188:v1']; (b) a registered domain catalog no tool emits is absent; (c) a KpiCard emitter plus a domain tool puts the Standard Profile first; (d) a tier-2 emitter is included; (e) a2ui_allowed_components is applied on the card path. In test_card_console.py::test_card_shape, assert the exact supportedCatalogIds list derived from the example agent's emits, and that any registered domain catalog the example tools never emit is absent.

### RT-009
- severity: medium
- file: docs/content-types.md (also DESIGN.md)
- description: Raised in three rounds. docs/content-types.md:83-84 still says 'The agent card advertises every catalog id in the A2UI extension params.supportedCatalogIds'. After GH-188 only catalogs of types some tool emits are listed (after the a2ui_allowed_components filter), and the list may be []. The doc contradicts DESIGN.md and the code; authors who register a domain card with no emitting tool will expect it advertised. Also, the DESIGN.md loop-policies paragraph (~line 474), which documents the sibling GH-155 final_summary behaviour, says nothing about the GH-194 post-tool empty-reply retry or its fixed notice.
- fix: Rewrite docs/content-types.md:83: the card advertises the catalog of each type a registered tool emits (Standard Profile first when a Profile type is emitted, after AGENT_SDK_A2UI_ALLOWED_COMPONENTS); a registered type no tool emits is not advertised; an agent with no emitting tools advertises []. Cite the GH-188 ruling URL. Add one sentence to DESIGN.md §loop-policies describing the GH-194 retry (one tools-off call, not a max_turns turn, counts toward the budget, fixed notice unless a card was delivered, LoopPolicies.empty_reply_retry) with the ruling URL.

### RT-010
- severity: low
- file: agent_sdk/agent/registry.py
- description: Raised in two rounds. With allow_extra_args=True on a tool whose input model sets extra="forbid", input_schema() (~line 720-727) advertises additionalProperties: true, but model_validate still rejects extra keys. Verified: the schema shows True and invoke({'a':1,'b':2}) raises ToolInputValidationError ('<extra>'). The advertised schema and the enforcement disagree (ruling: advertise true only for opted-out tools that actually accept extras).
- fix: Preferably raise ValueError at @tool registration when allow_extra_args=True is combined with an extra="forbid" input model. Otherwise have input_schema() advertise True only when extras are really accepted (allow_extra_args and extra != "forbid", or extra == "allow"). Add a test.
- codify: An opt-out flag and the model's own extra policy must be reconciled in one place, or the advertised schema and the enforced rule disagree.

### RT-011
- severity: low
- file: agent_sdk/agent/loop.py
- description: The GH-194 AC says 'No retry ... when sealed'. The retry condition (~line 1399) checks the deadline and token budget but not is_sealed(). The last seal check comes before the UsageEvent yield, and the consumer can await during that yield, so a seal can land before the retry call. The post-await re-check stops any fold, but a wasted model call is still made.
- fix: Add `and not is_sealed()` to the elif condition. Add a test for sealed-before-retry that expects no third model.calls entry.

### RT-012
- severity: low
- file: tests/test_gh194_empty_reply_retry.py (also tests/test_gh196_reject_unknown_tool_args.py)
- description: Raised in four rounds. Some ACs have no test. (a) GH-194 'No retry ... past the deadline': no test drives the deadline.exceeded() guard in the retry branch (budget, sealed-during-retry and no-tool-result are covered). (b) GH-196 'reuse_fields $ref tokens ... still validate (no false rejects)': the file has no ReuseKind field and no $ref: token; covered only indirectly by older reuse tests. (c) No test for the admin try-tool surface the CHANGELOG claims, and none for the extra="forbid" or aliased-field cases (see RT-001, RT-002).
- fix: Add (1) a GH-194 test with an injected clock (run_loop clock=) that passes policies.deadline_seconds after the tool turn: exactly 2 model calls, no notice TextEvent, DoneEvent ok=True; (2) a GH-196 loop test with a ReuseKind field called with a `$ref:<kind>:<label>` token after a resolving call: ok=True, no unknown_argument error; (3) admin POST try-tool with an extra key returns category 'validation' and names the key but not the value; (4) the forbid and alias cases.

### RT-013
- severity: low
- file: agent_sdk/agent/loop.py (also docs/tools.md)
- description: `artifact_delivered` is local to one run_loop call and set only at the loop's own ArtifactEvent site. A card delivered earlier in the same user turn but in another run_loop call is not seen: before an interrupt resume (a new run_loop call), or by the runner's deferred-result path (agent/runner.py ~1093). In those cases a blank post-tool reply still gets the 'could not write a reply' notice next to a delivered card, against the ruling ('skip the notice when a card was already delivered this turn').
- fix: Thread a 'card already delivered this turn' flag into run_loop, e.g. a keyword the runner sets from the task's artifacts for the current turn. Or document the per-call scope in docs/tools.md and the LoopPolicies comment.

### RT-014
- severity: low
- file: CHANGELOG.md
- description: Raised in two rounds. (a) The GH-194 Changed entry (line ~13) says the retry fires 'when the model ends a turn with no text and no tool call', leaving out the 'right after a tool result' condition and the no-notice-when-card-delivered case; read literally, every blank first reply is retried, which the code does not do (test_no_retry_without_tool_result). (b) The G2 entries repeat themselves: GH-194 under both Added and Changed, GH-196 under both Breaking and Added, GH-188 under both Added and Changed. (c) The GH-194 Changed file list leaves out docs/tools.md (LRN-202 file-list parity).
- fix: Keep one entry per issue under its main heading (Breaking for GH-196, Changed for GH-194/GH-188); delete the duplicate Added lines or make them short pointers. Reword GH-194: 'When the model's reply right after a tool result has no tool calls and only blank text, the loop makes one tools-off retry (no max_turns turn; tokens count toward the budget); if still blank or it fails, a fixed notice is emitted unless a card was already delivered.' Add docs/tools.md to its file list.
