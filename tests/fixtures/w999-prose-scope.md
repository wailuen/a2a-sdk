# w999 — RT-001 fixture: prose-form Creates:/Modifies: scope

Regression fixture for RT-001 (fix round): most w036/w039-style todos declare their real
Creates:/Modifies: scope entirely inside parenthetical prose on the Creates: line, with no
separate Modifies: field. This file mirrors that dominant shape (modeled on real todos in
workspace/todos/completed/w036-gh-issues.md and workspace/todos/active/w039-gh-issues.md) so
`extract_wave_scope` has a real, non-synthetic fixture to run against.

RT-006: T1-T4 below are clean path lists and cannot exercise the path-shape filter —
the real w039 file's dominant form interleaves genuine paths with identifier-in-backticks
prose (dotted attribute chains, bare constants, slash-commands) inside the SAME long
Creates: line, via inline `# RT-NNN:` annotation comments. T5 excerpts that shape verbatim
from w039's GH-135 Creates: line so this fixture can actually detect a path-shape
regression, not just a keyword-span one.

---

- [ ] `T1` first todo — parenthetical modify-list plus a trailing adds clause
  - Creates: (modifies `agent_sdk/routes/mcp.py`, `agent_sdk/routes/admin.py`, `agent_sdk/__init__.py`); adds `tests/test_t1.py`

- [ ] `T2` second todo — parenthetical modify-list only, no bare create at all
  - Creates: (modifies `agent_sdk/config.py`)

- [ ] `T3` third todo — bare Creates:/Modifies: form (the minority shape, still supported)
  - Creates: `src/tools/new_tool.py`
  - Modifies: `src/routes/mcp.py`

- [ ] `T4` fourth todo — a bare "modifies `path`" clause OUTSIDE any parenthetical, on the
      same Creates: line as a parenthetical one
  - Creates: (modifies `agent_sdk/app.py`); modifies `docs/content-types.md`; adds `tests/test_t4.py`

- [ ] `T5` fifth todo — RT-006: real paths interleaved with identifier-in-backticks prose
      on one long Creates: line, excerpted verbatim from w039-gh-issues.md's GH-135 item
  - Creates: (modifies `agent_sdk/agent/registry.py`, `agent_sdk/agent/loop.py`, `agent_sdk/routes/mcp.py`, `agent_sdk/routes/admin.py`, `agent_sdk/__init__.py`, `agent_sdk/contrib/commitments/executor.py`); adds regression test (`tests/test_contrib_commitments.py`, `tests/test_rt004_catchall_frame_parity.py`)  # RT-003: the Reuses: note below mandates updating mcp.py/admin.py's parity-mirrored ValidationError branches — those edits are real deliverables of this todo and must be declared here, not only named in prose, or they evade wave.allScope. RT-007: the Reuses: note also mandates the FOURTH C-012 surface — contrib/commitments/executor.py's `_fire` — get the identical ToolInputValidationError branch, closing the offendingUndeclaredScope gap GH-132's fourth-blind-spot fix (same wave) was built to catch.
