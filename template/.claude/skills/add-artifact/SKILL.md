---
name: add-artifact
description: "Migrate a hardcoded agent persona (persona.py or inline string) to src/artifacts/system.md with Jinja2 templating, loaded by ArtifactLoader at startup. Works for SDK agents (artifacts_dir= on Agent) and pre-SDK agents (ArtifactLoader standalone). No behaviour regression — the same string reaches the model."
---

# /add-artifact — move the agent persona to src/artifacts/

Extracts a hardcoded system prompt into `src/artifacts/system.md`, replacing
the Python string with a Jinja2 template loaded at startup via `ArtifactLoader`.
The rendered output is identical to the original; nothing on the wire changes.

Run from inside an agent repo. **No git commit** unless the user asks.

## Usage

```
/add-artifact [--vars <var1,var2,...>]
```

- `--vars` — comma-separated Jinja2 variables the template needs at render time
  beyond the SDK built-ins (`agent_name`, `agent_version`). Examples:
  `today`, `gap_phrases`, `now_utc`.

## When to use

| Situation | Action |
|-----------|--------|
| Agent has `src/persona.py` with a `PERSONA` constant | `/add-artifact` — full migration |
| Agent has inline `_SYSTEM_PROMPT_TEMPLATE` in `loop.py` / `prompts.py` | `/add-artifact` — extract and migrate |
| Agent needs `{{ today }}` or other runtime vars in the prompt | `/add-artifact --vars today` |
| Agent is pre-SDK (own Bedrock loop) | `/add-artifact` — uses `ArtifactLoader` standalone |

## Phase 1 — Locate the prompt

1. Find the current system prompt. Common locations:
   - `src/persona.py` → `PERSONA` constant (SDK agents, template)
   - `src/agent/prompts.py` → `SYSTEM_PROMPT_TEMPLATE` (e.g. m365)
   - `src/agent/loop.py` → `_SYSTEM_PROMPT_TEMPLATE` inline string (pre-SDK agents)
   - Inline string in the `Agent(persona=...)` constructor call

2. Note any computed values injected into the prompt:
   - Python f-string expressions (e.g. `f"... {_gap_noun_phrases()} ..."`)
   - `.format()` calls (e.g. `TEMPLATE.format(today=today_iso, ...)`)
   These become Jinja2 `{{ variable }}` references in the artifact.

3. Note when variables are resolved:
   - **Startup-time** (once at boot): `agent_name`, `agent_version`, computed
     constants like `_gap_noun_phrases()` → inject via `artifact_vars=` on `Agent`
   - **Call-time** (per request): `today`, `now_utc`, `user_tz` → call
     `ArtifactLoader.render("system", today=..., ...)` inside the loop function

## Phase 2 — Write src/artifacts/system.md

4. Create `src/artifacts/` if it does not exist.

5. Write `src/artifacts/system.md`:

```markdown
---
name: system
description: <one-line description of this agent's persona>
---

<prompt body — paste from the source, converting injected values to {{ variable }}>
```

**Variable syntax rules:**
- Scaffold placeholders in template files: `{{AGENT_NAME}}` (no spaces, UPPERCASE) —
  replaced once at agent creation. Leave these as-is; they are not Jinja2.
- Runtime Jinja2 variables: `{{ variable_name }}` (with spaces, lowercase) — rendered
  by `ArtifactLoader.render()` at load time.
- There is no conflict: the scaffold tool replaces `{{UPPERCASE}}` only.

**Conversion examples:**

| Python source | Artifact (Jinja2) |
|---------------|-------------------|
| `f"... {_gap_noun_phrases()} ..."` | `... {{ gap_phrases }} ...` |
| `TEMPLATE.format(today=today_iso)` + `\nToday's date: {today_iso}` | `Today's date: {{ today }}` (inline in template body) |
| `TEMPLATE.format(user_tz=user_tz_label, ...)` | `{{ user_tz }}`, `{{ utc_offset }}`, etc. |
| Static string, no injections | Copy verbatim; no `{{ }}` needed |

6. **Frontmatter fields:**
   - `name: system` — `ArtifactLoader` loads this by stem name; always `system` for
     the main persona.
   - `description:` — brief label; not injected into the prompt.

## Phase 3 — Wire the loader

### SDK agents (use `Agent(artifacts_dir=...)`)

7. In `main.py` (or `agent.py`):

```python
# Before
from .persona import PERSONA

agent = Agent(
    settings=make_settings(),
    persona=PERSONA,
    skills_dir=Path(__file__).parent / "skills",
    ...
)
```

```python
# After
agent = Agent(
    settings=make_settings(),
    artifacts_dir=Path(__file__).parent / "artifacts",
    # artifact_vars only needed when the template has {{ variables }} that are
    # computed at startup (not call-time):
    artifact_vars={"gap_phrases": _gap_noun_phrases()},
    skills_dir=Path(__file__).parent / "skills",
    ...
)
```

SDK built-in vars injected automatically: `agent_name`, `agent_version`.
Add `artifact_vars=` only for agent-specific computed values.

8. Delete `src/persona.py` (and any conftest.py / test imports of it).
   Update tests that used `persona=PERSONA` to `artifacts_dir=...` instead:

```python
# tests/conftest.py — before
from src.persona import PERSONA

agent = Agent(settings=settings, persona=PERSONA, ...)

# after
agent = Agent(
    settings=settings,
    artifacts_dir=Path(__file__).parent.parent / "src" / "artifacts",
    ...
)
```

### Pre-SDK agents (standalone `ArtifactLoader`)

9. In the file that defines `_SYSTEM_PROMPT_TEMPLATE` or imports `prompts.py`,
   replace the template string with an `ArtifactLoader` instance:

```python
# Before (e.g. src/agent/loop.py)
from src.agent.prompts import SYSTEM_PROMPT_TEMPLATE   # or inline string

# ... inside _build_system_blocks():
persona_text = SYSTEM_PROMPT_TEMPLATE.format(today=today_iso, now_utc=..., ...)
```

```python
# After
from pathlib import Path
from agent_sdk import ArtifactLoader

# Module-level — compiles Jinja2 templates once at import
_artifacts = ArtifactLoader(Path(__file__).parent.parent / "artifacts")

# ... inside _build_system_blocks():
persona_text = _artifacts.render("system", today=today_iso, now_utc=..., ...)
```

- Create the `ArtifactLoader` **at module level** (one-time template compilation).
- Call `.render()` **at call time** (per request) with whatever variables the
  template uses — cheap because templates are already compiled.
- Delete `src/agent/prompts.py` (or the inline template variable in `loop.py`).

## Phase 4 — Verify no regression

10. Run the agent's test suite:

```bash
pytest tests/ -x -q
```

11. If the agent has a `conftest.py` that imported `PERSONA`, fix it (step 8).

12. Boot the agent and confirm the system prompt is identical:

```bash
DEV_MODE=true uvicorn src.main:app --port 8000
# SDK agents: /agent-verify includes a system-prompt smoke
# Pre-SDK agents: send a test message and confirm persona behaviour
```

13. For SDK agents, the system prompt is accessible at `app.state.system_prompt` —
    print it in a test to verify it matches the original verbatim:

```python
def test_persona_unchanged(app):
    assert "You are AlphaGeo" in app.state.system_prompt
```

## Rules

- **Zero regression.** The rendered artifact must produce the same string the
  model received before. Verify by assertion if in doubt.
- **No new logic in the artifact.** Jinja2 variables are substitution-only.
  Computed values (like `_gap_noun_phrases()`) stay in Python and are passed in
  via `artifact_vars=` or `.render()` kwargs — never recomputed in the template.
- **One file per prompt surface.** `system.md` is the main persona. If an agent
  has separate tool-context or few-shot prompts hardcoded elsewhere, each gets
  its own `.md` file and is loaded by name: `_artifacts.render("tool-context")`.
- **Pre-SDK agents: add `agent_sdk` to dependencies** if not already present,
  since `ArtifactLoader` is imported from it.
- **Do not touch pre-SDK agents that are not ready to migrate.** This skill is
  opt-in per agent. The SDK `persona=` path remains supported indefinitely.
