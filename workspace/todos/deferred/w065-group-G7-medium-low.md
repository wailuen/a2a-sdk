# w065 — Group G7 — deferred medium/low findings

- Wave: w065
- Scope: unit:G7
- Date: 2026-10-24

Non-blocking — these did not block w065's archive. Address opportunistically or fold into a future wave.

Findings are deduped by file+description across all redteam rounds. Unicode characters are written as `\uXXXX` escapes on purpose.

## 1. [medium] U+202E only in the "must not appear" list, not in the hostile input — tests/test_gh212_id_safe_text.py:38, :159, :165
- Problem: the GH-250 AC says to add U+202E to the GH-212 hostile set. It went only into the asserted-absent loop (line 165). `HOSTILE_STANDALONE` (line 38) has no U+202E, so `"‮" not in text` can never fail. Nothing end-to-end checks that bidi characters are dropped from the standalone `id:` line or the is_id cell on MCP or A2A.
- Fix: add `‮` (and ideally `⁦`) to `HOSTILE_STANDALONE`, as escapes. Add `‮` to the standalone `id_line` loop (line 159) too, so both the `standalone_hostile` and `is_id_hostile` wire renders prove the drop.
- Codify: a hostile-set test must put the hostile character in the INPUT. Adding it only to the "must not appear" list makes the assertion pass without testing anything.
- sdkCandidate: true

## 2. [medium] `safe_block_text` skips `drop_format_chars` — agent_sdk/common/redact.py:65, :303
- Problem: the `drop_format_chars` docstring says every wire-bound `safe_*_text` helper calls it first. `safe_block_text` (line 303) and `safe_error_text` do not. `safe_block_text("a‮b")` returns the string unchanged. Through `content_types._sanitize_block` it renders `MarketBriefing.prose` and `section.content` (content_types.py:1002/1015) into MCP `content[0].text`, so Trojan-Source bidi characters (U+202E, U+2066-2069) still reach the wire. The C-078 row also leaves it out without saying why.
- Fix: call `drop_format_chars(value)` first in `safe_block_text` (it keeps `\n` and `\t`; neither is Cf), add it to the C-078 row, the CHANGELOG and a GH-250 bidi test. Or narrow the docstring and C-078 row to the exact helpers covered and record why block/error text is exempt.
- Codify: a docstring that says "every X helper does Y" must be checked by grepping every function matching that name pattern. Block/markdown sanitisers are wire-bound too.
- sdkCandidate: true

## 3. [medium] `X-Agent-Credentials` header parses with bare `json.loads` — agent_sdk/credentials/forwarding.py:75
- Problem: `docs/protocols.md:169` says "Every JSON ingress parses with `loads_strict`", and DESIGN.md says the same. The `X-Agent-Credentials` header (parsed on every MCP, A2A and AG-UI request) still uses `json.loads` and catches only ValueError/UnicodeDecodeError. Verified on Python 3.12 (supported by `requires-python`): `parse_header(b64("[" * 16000))` raises RecursionError instead of returning `{}`, so the route answers 500 — the same C-040 bypass class GH-250 item 2 fixed for the Graph webhook. Impact is limited by the 16 KB cap, dict/str type checks, and Python 3.14 not recursing, but the documented invariant is false.
- Fix: parse with `loads_strict(decoded)` and catch `ValueError` (covers JSONDecodeError / NestingTooDeep / UnicodeDecodeError), returning `{}` fail-closed. Add a deep-header test. Or narrow the protocols.md and DESIGN.md sentences to the body ingresses they list. Also note the Graph webhook answers 202-drop, not the -32700/RUN_ERROR text DESIGN.md lists next to it.
- Codify: before a doc claims "every JSON ingress" uses the strict parser, grep every `json.loads` on request-derived data (bodies, headers, query params).
- sdkCandidate: true

## 4. [medium] GH-235 regression tests deleted in rewrite — tests/test_gh235_nested_json_and_resume.py:167
- Problem: the rewrite removed shipped coverage the G7 AC never asked to retire: `test_oauth_register_nested_is_invalid_client_metadata` (unauthenticated /oauth/register deep body), the object-nesting depth case (`{"a":` x300), and `test_a2a_deep_metadata_never_breaks_task_list`. Nothing else covers deep nesting on /oauth/register or object (not array) nesting through `loads_strict`; test_gh250 only sends arrays.
- Fix: restore the three tests through the real parser (no shim). Add an object-nested body (e.g. `{"a":` x65) to the DEPTHS-style surface tests so `_check_depth`'s dict branch runs on at least one route.
- Codify: when rewriting a test file to drop a shim, diff the old test names and keep every regression test the todo did not explicitly retire.
- sdkCandidate: true

## 5. [low] `NestingTooDeep` breaks copy/pickle — agent_sdk/common/json_strict.py:71-72
- Problem: the public `NestingTooDeep` (in `__all__`) overrides `__init__` with no args but inherits `JSONDecodeError.__reduce__`, which rebuilds it as `cls(msg, doc, pos)`. `copy.copy(exc)` and pickle both raise `TypeError: __init__() takes 1 positional argument but 4 were given` (verified). Breaks multiprocessing, QueueHandler log records with exc_info, exception-group copying. `str(exc)` is also `nesting too deep: line 1 column 1 (char 0)`, not the fixed text.
- Fix: `def __init__(self, msg: str = NESTING_TOO_DEEP_MESSAGE, doc: str = "", pos: int = 0) -> None: super().__init__(NESTING_TOO_DEEP_MESSAGE, "", 0)` (ignore passed values so no body data comes back), or define `__reduce__` returning `(type(self), ())`. Add a copy/pickle round-trip test.
- sdkCandidate: true

## 6. [low] Raw invisible bidi/format characters in test source — tests/test_gh250_core_hardening.py:259, :281, :298
- Problem: string literals embed raw U+202E, U+2066, U+2069, U+200B. GH-250 item 7 flagged this exact problem for U+2028 in test_gh212. Raw U+202E in source is itself a Trojan-Source pattern: editors, diffs and GitHub show the lines differently from their bytes.
- Fix: use escapes: `BIDI = "a‮b⁦c⁩d​e"`, `message = "Use‮ AAPL"`, `["\x07 ", "‮", "‮⁦ \x00", ""]`. Optionally add a repo test that fails on any raw Cf/Zl/Zp character in tests/*.py.
- sdkCandidate: true

## 7. [low] `pytest.raises(Exception)` too loose — tests/test_gh250_core_hardening.py:293
- Problem: `test_safe_value_error_hint_drops_bidi` catches any Exception. If the validator stops raising a pydantic ValidationError, the test fails for an unrelated reason or passes by accident. GH-250 item 7 removed this pattern from test_gh230; this file brings it back.
- Fix: `with pytest.raises(ValidationError) as info:` (`from pydantic import ValidationError`), and move the in-function `field_validator` and `safe_validation_message` imports to module level.
- sdkCandidate: true

## 8. [low] Unused import — tests/test_gh250_core_hardening.py:34
- Problem: `from .test_ag_ui import run, run_body` is never used; the AG-UI depth tests call `client.post` directly.
- Fix: delete the import, or use `run(client, ...)` in the AG-UI depth tests so frame parsing is shared.
- sdkCandidate: true

## 9. [low] Docs miss the new Cf-drop contract for `safe_line_text` / `safe_cell_text` — docs/content-types.md:210, :257
- Problem: GH-250 makes both helpers drop Unicode format/bidi characters. Only the `safe_id_text` paragraph was updated. The Standalone slots (`safe_line_text`) and `safe_cell_text` sections still list only line-break and control handling, so developers won't expect ZWJ emoji sequences or Persian ZWNJ to be removed from titles and cells.
- Fix: add to both sections: "Unicode format and bidi characters (category Cf, e.g. U+202E, ZWJ, ZWNJ) are dropped (GH-250)."
- sdkCandidate: true
