# w063 — group G1 deferred medium/low findings

- Wave: w063
- Scope: unit:G1
- Date: 2026-10-24

Non-blocking — these did not block w063's archive. Address opportunistically or fold into a future wave.

All findings are in `tests/test_gh233_workflow_scripts_parse.py`. Duplicates across redteam rounds were merged (by file + description).

## 1. Failure message hides node stderr and the mirror path (low, sdkCandidate) — RT-001 / RT-002

- Line: 42
- Quote: `assert result.returncode == 0, f"{path.name} has a JS syntax error"`
- Problem: On failure, node's stderr (line, column, error text, e.g. `SyntaxError: Unexpected identifier 's'`) is dropped. `path.name` is ambiguous because `acceptance-api.js` and `wave-cycle.js` exist in more than one mirror folder.
- Fix: `f"{path.relative_to(REPO_ROOT)} has a JS syntax error:\n{result.stderr.replace(str(wrapped), str(path))}"`. Reported line numbers are off by one due to the wrapper line; say so in the message or subtract 1.

## 2. Discovery guard does not require `.claude/workflows/` (low, sdkCandidate) — RT-003

- Line: 46
- Quote: `assert any(p.parent == REPO_ROOT / "harness" / "workflows" for p in SCRIPTS)`
- Problem: Only `harness/workflows/` is guarded. If `.claude/workflows/` is renamed or emptied, `sdk-wave.js` and runtime `wave-cycle.js` silently drop out of the parse check. The AC names `.claude/workflows/` as required.
- Fix: Also assert `REPO_ROOT / ".claude" / "workflows" / "sdk-wave.js"` is in SCRIPTS and that `.claude/workflows` yields at least one script. Keep `template/` conditional on presence.

## 3. `export` strip is start-of-file only; text I/O uses locale encoding (low, sdkCandidate) — RT-004 / RT-002

- Lines: 36–39
- Quote: `src = re.sub(r"^\s*export\s+", "", path.read_text(), count=1)`
- Problem (a): No MULTILINE flag, so only an `export` at the very start of the file is removed. A script opening with a comment/header, or with a second `export`, fails with a spurious syntax error (loud failure, not a silent pass).
- Problem (b): `read_text()` / `write_text()` use the locale default encoding. Scripts contain non-ASCII (arrows, en-dash in `1–10`); on a non-UTF-8 host this raises UnicodeDecodeError unrelated to JS syntax.
- Fix: Pass `encoding="utf-8"` to `path.read_text()` and `wrapped.write_text()`. Use `re.sub(r"^export\s+", "", src, count=1, flags=re.M)`, or mirror exactly how the Workflow runtime loads a script and document that rule in the docstring.
