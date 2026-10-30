# w069 — deferred medium/low findings (unit:G1)

- Wave: w069
- Scope: unit:G1
- Date: 2026-10-30

Non-blocking — these did not block w069's archive. Address opportunistically or fold into a future wave.

## RT-001 (medium) — agent_sdk/agent/loop.py:1149
Quote: `current = args[0] if args else None`

For a fixed-length tuple, the loc walk always takes the first type argument, whatever the index. Since GH-275 that annotation picks the advertised choices, so `t: tuple[Literal["a","b"], Literal["c","d"]]` with a bad value at index 1 renders `t.1 — must be one of: "a", "b"`. Wrong list: a client retrying with "a" fails again. Verified with a probe script. Breaks the AC rule that values come from the declared annotation at the resolved loc.

Fix: in the int-segment branch, when origin is tuple and args do not end in `Ellipsis`, use `args[seg]` if `0 <= seg < len(args)`, else None (clean=False). Keep `args[0]` only for `tuple[X, ...]`, list, set, frozenset. Add a test: two-Literal tuple, bad value at index 1 lists "c", "d".

Codify: when a loc walk chooses which values to show, each container shape must map index to annotation exactly; a fixed tuple's index i is args[i], not args[0].

SDK candidate: yes

## RT-002 (medium) — tests/test_gh275_allowed_values.py:150
Quote: `def test_custom_error_on_plain_str_keeps_fallback_and_no_echo() -> None:`

Todo AC (6) and SI-2 note (d) require test (6) to show the PydanticCustomError ctx marker is absent from both tool-result text and captured logs. The landed test calls safe_validation_message directly and checks only the returned text. No log capture for the ctx-marker case; no wire surface (MCP tools/call, admin try-tool, loop) exercised. The only log assertion is in the MCP test, for `ceased_desc`, not `ctx["expected"]`.

Fix: add a wire test registering a tool whose input model has a field validator raising `PydanticCustomError("literal_error", ..., {"expected": MARKER})`. Call over MCP tools/call under `sdk_caplog("agent_sdk", logging.DEBUG)`; assert MARKER absent from `result.content[0].text` and every captured record's message and args.

Codify: when a todo AC names two places a secret must not appear (wire text and logs), the test must capture and assert both.

SDK candidate: yes

## RT-003 (medium) — tests/test_gh275_allowed_values.py:227
Quote: `assert _skill_catalog(skills) == cap_whole_entries(entries, _MAX_SKILL_CATALOG_LEN)[0]`

The "skill catalog unchanged" test compares `_skill_catalog` with the same helper it now calls, so it is true by construction. It will not fail if C-075 changes catalog text (breaks LRN-560). tests/test_gh205_mcp_skills.py only checks the tail (`…and \d+ more`, `endswith("…and 1 more")`). The AC "output stays byte-identical" is unguarded.

Fix: pin a literal expected string — e.g. 20 skills with fixed names/descriptions, hard-code the exact pre-GH-275 catalog text (kept entries, `; ` separators, `…and N more`), assert equality. Or keep a frozen copy of the old fit loop as a reference oracle.

Codify: a "behaviour unchanged after refactor" test must compare against a frozen literal or independent oracle, never the new shared helper.

SDK candidate: yes

## RT-004 (low) — agent_sdk/agent/loop.py:1219
Quote: `raw = json.dumps(value)`

`json.dumps` defaults to `allow_nan=True`, so a float Literal/Enum value of inf or nan renders as `Infinity`/`NaN` (verified: `must be one of: 1.5, Infinity`). Not valid JSON; client cannot send it back. docs/tools.md says non-JSON values keep the fallback.

Fix: `json.dumps(value, allow_nan=False)`; the existing `except (TypeError, ValueError)` turns it into the fallback. Or skip that value and count it in `omitted`.

SDK candidate: yes

## RT-005 (low) — agent_sdk/agent/loop.py:1104
Quote: `def _redact_loc(loc: tuple[Any, ...], err_type: str, model: type[BaseModel] | None) -> str:`

`_redact_loc` has no caller in agent_sdk/ or tests/ (safe_validation_message calls `_walk_loc` directly) — dead code. safe_validation_message docstring still points to `_redact_loc` and omits the GH-275 allowed-values phrase. `_unwrap_annotation` docstring omits the new Annotated stripping and recursion.

Fix: delete `_redact_loc` or keep as a documented alias. Point the safe_validation_message docstring at `_walk_loc` and add the `literal_error`/`enum` `must be one of:` rule. Update `_unwrap_annotation` docstring for Annotated strip and nested Union recursion.

SDK candidate: yes

## RT-006 (low) — agent_sdk/common/text.py:21
Quote: `reserved in every fit check, so the result never exceeds ``limit``.`

Docstring promises the result never exceeds `limit`. When `limit` is shorter than the tail, the bare tail is returned anyway: `cap_whole_entries(["x"*10], 5)` returns `"…and 1 more"` (11 chars). Same when an entry is skipped and `limit` is under ~11. Registry row C-075 repeats the claim.

Fix: weaken the docstring and C-075 row ("except when `limit` is shorter than the tail itself"), or document a minimum `limit` and raise ValueError below it. Add a unit test for the chosen behaviour.

SDK candidate: yes

## RT-007 (low) — docs/tools.md:215
Quote: `characters after cleaning) is left out and counted in that tail, never shown cut.`

The skip rule measures JSON-encoded text with `ensure_ascii=True`, quotes and escapes included, not the value "after cleaning". A 50-char CJK string becomes ~302 chars as `\uXXXX` escapes and is skipped. A 255-char ASCII value is skipped once its two quotes push it past 256. Docs promise a value is shown when its cleaned length is at most 256.

Fix: reword — "A value whose JSON form (with non-ASCII characters escaped as \uXXXX, quotes included) is longer than 256 characters is left out...".

SDK candidate: yes

## RT-008 (low) — agent_sdk/agent/loop.py:1156
Quote: `if isinstance(ann, type) and issubclass(ann, BaseModel):`

The BaseModel branch now tests the unwrapped annotation. For a non-nullable union, `_unwrap_annotation` returns the first member, so a union-tag loc segment (`'A'` for `n: A | B`, or a discriminator like `'dog'`) is looked up in the first member's fields. Normally it misses and renders `<key>`; but if the first member has a field named like the tag, the walk follows that field and can list the wrong member's choices. Safe for SI-2 (only declared names rendered), but values can be wrong.

Fix: in `_walk_loc`, unwrap only when Union minus None has exactly one member (Optional). For two or more real members, treat the segment as unresolved: render `<key>`, clean=False, as before GH-275.

SDK candidate: yes

---

Resolved before release (2026-10-30, by hand): RT-001 fixed in agent_sdk/agent/loop.py (fixed-length tuple index uses args[seg]; tests test_fixed_tuple_uses_annotation_at_index / test_variadic_tuple_uses_item_annotation). RT-002 fixed (test_mcp_custom_ctx_expected_never_echoed: MCP wire + logs). RT-003 fixed (skill catalog compared with a frozen copy of the v0.25.0 fit loop). Lows RT-004..RT-008 not filed.
