# w064 — unit:G5 — deferred medium/low findings

- Wave: w064
- Scope: unit:G5
- Date: 2026-10-24

> Non-blocking — these did not block w064's archive. Address opportunistically or fold into a future wave.

Findings were raised across redteam rounds; IDs were reused between rounds, so round tags (r1/r2) disambiguate. Where two rounds reported the same file+issue they are merged into one item.

## Medium

### 1. Raw U+2028 in test string (r1 RT-003) — sdkCandidate
- File: `tests/test_gh212_id_safe_text.py:158`
- Quote: `for ch in "|<>[]\x07\x1b<raw U+2028>\r":`
- Issue: The string holds a raw, invisible U+2028 (LINE SEPARATOR). The AC asks for the escape ` `. `splitlines()` treats the raw char as a line break, so viewers and line-based tools disagree on line numbers.
- Fix: Replace the raw char with the ` ` escape.

### 2. test_builtin_codes_render_code_not_generic only half cleaned (r1 RT-004, r2 RT-002) — sdkCandidate
- File: `tests/test_gh230_safe_value_error.py:184` (AC range 161-190, GH-242)
- Quote: `BaseModel.model_validate  # noqa: B018`
- Issue: Dead expression and in-function `from pydantic import Field` remain. Both try blocks lack an else branch: if `C.model_validate` stops raising, the `too_long` assertion is silently skipped; if `L` stops raising, the test dies with NameError instead of a clear assertion.
- Fix: Delete the dead expression; move `Field` to module imports; replace both try/except blocks with `with pytest.raises(ValidationError) as ei:` and assert on `safe_validation_message("t", ei.value, ...)`.
- Codify: A test that asserts inside `except` passes silently when nothing is raised. Use pytest.raises so the "no error" case fails.

### 3. docs/content-types.md still contradicts is_id column (r1 RT-005 medium, r2 RT-005 low) — sdkCandidate
- File: `docs/content-types.md:240`
- Quote: `control characters are neutralised). Never join an id into a row with other`
- Issue: Says "Never join an id into a row with other fields" right after describing is_id cells, which are joined with ` | ` into a row. Stated leftover risk names only `( )` and `=`; GH-241 lists spaces, `:` and `=`, and safe_id_text also keeps `,` byte-exact (e.g. `x, Called down: 99%` is not covered).
- Fix: Narrow the rule to "Never join an id into the same slot or cell as other text (an inline `(id: ...)` or `source <id>`)"; state that an is_id table cell is the supported way to place an id in a row; list the full set left as written inside an is_id cell: `( ) = : ,` and single spaces.

### 4. Private bidi/format-char stripper outside C-034/C-007 (r1 RT-006, r2 RT-003) — sdkCandidate
- File: `agent_sdk/agent/loop.py:1180`
- Quote: `def _drop_format_chars(text: str) -> str:`
- Issue: AC said use C-034 `safe_line_text` with no new stripper. A new private Cf/bidi stripper was added in loop.py, unregistered. The same Trojan-Source class (U+202E, U+2066-2069) still passes `safe_line_text`, `safe_cell_text`, `safe_id_text`, which feed MCP `content[0].text` titles, cells and is_id cells. The GH-212 hostile set has no bidi char, so the gap is untested.
- Fix: Move the Cf drop into `agent_sdk/common/redact.py` beside C-034 (named helper e.g. `drop_format_chars`, or `strip_format=True` on `safe_line_text`); call it from `_validation_phrase`; register in `workspace/components/README.md`. File a follow-up SDK issue on extending the bidi drop to `safe_cell_text`/`safe_id_text`; add U+202E to HOSTILE_STANDALONE once decided; reference the issue from the C-050 row.
- Codify: A new character class that must not reach the wire belongs in the shared redact helpers (C-034/C-007), not in a private function at one call site.

### 5. Hostile-hint tests only check absence, not survival (r1 RT-007) — sdkCandidate
- File: `tests/test_gh230_safe_value_error.py:346`
- Quote: `assert not _bad_chars(phrase)`
- Issue: Unit, MCP, A2A, AG-UI hostile-hint tests only check bad chars and MARKER are absent. None checks the readable part survives (e.g. `Use AAPL`, `red hint`). A regression that always returns the generic phrase or drops the error passes. The A2A test does not check an error reached the task.
- Fix: Parametrize each hostile hint with expected cleaned text, e.g. (`'\x07\x1b[31mred\x1b[0m hint'`, `'[31mred [0m hint'`) and (BIDI+`'Use AAPL'`+BIDI, `'Use AAPL'`). Assert it appears in the unit result, MCP content text, A2A tool result and AG-UI TOOL_CALL_RESULT. Assert GENERIC only for cases that sanitise to empty.

### 6. CHANGELOG files a breaking change and a new export under Fixed (r2 RT-001, r1 RT-009 changelog part) — sdkCandidate
- File: `CHANGELOG.md:13`
- Quote: `- GH-241: the `SafeValueError` hint is sanitised in `_validation_phrase` ... (**behaviour change**: a subclass with no `message` now fails at definition). `agent_sdk.safe_joined_id_text` is exported ...`
- Issue: Backward-incompatible change to public `agent_sdk.SafeValueError` (released 0.20.0) is under `### Fixed`. Code like an intermediate `class DomainError(SafeValueError): pass` now raises TypeError at import. The new export `safe_joined_id_text` is also under Fixed. 0.20.0 precedent (GH-205) used `### 🔴 Breaking changes`.
- Fix: Put the `__init_subclass__` TypeError under `### 🔴 Breaking changes` in [Unreleased] with a Migration callout (give every intermediate subclass a non-blank `message`). Put the `safe_joined_id_text` export under `### Added`. Keep only hint sanitising under Fixed.
- Codify: A new definition-time check on an exported base class is a breaking change. It goes under Breaking changes with a migration note, never under Fixed.

## Low

### 7. Definition-time guard uses only strip(); redundant lookup; docstrings stale (r1 RT-008 sdkCandidate, r2 RT-008 not sdkCandidate)
- File: `agent_sdk/models/errors.py:79`
- Quote: `hint = cls.__dict__.get("message", getattr(cls, "message", None))`
- Issue: Guard uses only `str.strip()`; a message like `'\x07 '` or bidi-only passes but always renders the generic phrase. GH-230 ruling says detectable cases should fail at boot. The two-step lookup equals `getattr(cls, "message", None)` and wrongly suggests inherited values are treated differently. `safe_validation_message` docstring (loop.py:1216) and `SafeValueError` docstring omit the sanitising and TypeError guard.
- Fix: Run the same sanitiser `_validation_phrase` uses (once in redact.py, see item 4) in `__init_subclass__`; raise TypeError when empty. Use `getattr(cls, "message", None)`. Keep the runtime fallback for attributes changed after definition. Add docstring sentences: "A subclass whose message is not a non-blank str raises TypeError at definition" and "the hint passes safe_line_text and a format-char drop; an empty result shows the generic phrase".

### 8. safe_joined_id_text export not pinned by a test (r1 RT-009, r2 RT-006) — sdkCandidate
- Files: `agent_sdk/__init__.py:54` (`"safe_joined_id_text",`), `tests/test_gh212_id_safe_text.py:116` (`assert agent_sdk.safe_id_text is safe_id_text`)
- Issue: New stable-core export with no test; `test_exported`, `test_public_api_exports`, `test_rt009` do not list it, so removal would go unnoticed.
- Fix: Add `assert agent_sdk.safe_joined_id_text is safe_joined_id_text` and `"safe_joined_id_text" in agent_sdk.__all__` to `test_exported`. (CHANGELOG placement: see item 6.)

### 9. Wire-level SI-2 check exempts CR/LF/TAB; no arrival check (r2 RT-004) — sdkCandidate
- File: `tests/test_gh230_safe_value_error.py:427`
- Quote: `assert not [c for c in _bad_chars(payload) if c not in "\n\r\t"], repr(payload)`
- Issue: MCP/A2A/AG-UI check cannot catch a hint that injects a line break. No surface test checks the sanitised hint or generic phrase arrived. `_assert_clean(_flatten(task))` (line 468) likely has no tool error text in it.
- Fix: Locate the specific error string (MCP `content[0].text`, toolResult text block in `fake.calls[1]`, TOOL_CALL_RESULT content); assert it contains the expected sanitised hint or GENERIC; then assert no Cc/Cf/Zl/Zp char at all on it, with no CR/LF exemption.

### 10. NoMessage and EmptyMessage now identical (r2 RT-007) — not sdkCandidate
- File: `tests/test_gh230_safe_value_error.py:43`
- Quote: `NoMessage.message = ""`
- Issue: After the `__init_subclass__` guard both are defined with "placeholder" then set to `''`. NoMessage models no reachable case; redundant, misleading name.
- Fix: Drop or rename NoMessage (message changed after definition). Add a case where a subclass's `message` is deleted after definition so it falls back to the base `''`.
