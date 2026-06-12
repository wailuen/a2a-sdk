---
name: diagnose
category: core
description: "Structured runtime triage for agent-sdk agents: classifies the failure layer (config, SDK boot, domain code, protocol surface, credentials, upstream), pinpoints root cause, and produces a fix prescription — without fixing silently."
---

# /diagnose — Runtime triage

Structured root-cause analysis when something is broken. Reads code, probes
endpoints, reads logs, and classifies the failure to the exact layer before
suggesting a fix. Advisory only — never edits.

## Usage

```
/diagnose [symptom]
```

Examples:
- `/diagnose` — interactive triage (asks for the symptom)
- `/diagnose boot` — agent won't start
- `/diagnose 401` — all requests return 401
- `/diagnose tool <tool-name>` — a specific tool is erroring
- `/diagnose source <source-name>` — a source adapter is failing
- `/diagnose a2a` — A2A endpoint conformance issue

## Failure layers (classify first)

| Layer | Symptoms | Probe |
|-------|----------|-------|
| **L1 Config** | `KeyError`, `ValidationError` at boot | Read `.env`, `src/config.py`, `make_settings()` |
| **L2 SDK boot** | `build_app()` raises, uvicorn exits immediately | Read uvicorn stdout/stderr; run boot with captured output |
| **L3 Domain wiring** | Tool or source not found; `build_app()` registration error | Read `src/main.py` `toolsets=` and `register_source(...)` calls |
| **L4 Credentials** | Source `health_check` fails; `CredentialError` | `POST /admin/sources/<name>/health`; check store, not env |
| **L5 Protocol surface** | 401/403/404/422 from A2A, MCP, AG-UI; malformed response | Targeted curl probes; read route files |
| **L6 Upstream** | Tool call times out or returns error; 5xx from source | Health-check the upstream service directly; check `allowed_hosts` |
| **L7 Test** | Tests fail but agent boots OK | Run `pytest -v` scoped to the failing test; read the assertion |

## Steps

1. **Collect the symptom.** Parse `$ARGUMENTS`. If none, ask:
   "What is breaking? (boot error / HTTP status / tool name / source name / other)"

2. **Classify to a layer** using the table above. State the hypothesis:
   "Hypothesis: L<N> — <layer name>"

3. **Run layer-specific probes:**

   **L1 Config:**
   - Read `.env` (check only presence of keys, not values)
   - Run: `python -c "from src.config import make_settings; make_settings()"` — if
     it raises, the traceback names the exact missing/invalid field.

   **L2 SDK boot:**
   - Run from the agent root (cwd matters for relative imports):
     `cd <agent-root> && DEV_MODE=true .venv/bin/python -c "from src.main import app"`
     — captures import-time errors without starting uvicorn.
   - If that passes: boot uvicorn for 5 s (stdout/stderr to a temp file), kill,
     report what was printed.

   **L3 Domain wiring:**
   - Read `src/main.py`. List: every `toolsets=[...]` entry, every
     `register_source(...)` call. Verify each class is imported and the module
     exists. A missing import = L3 finding.

   **L4 Credentials:**
   - `POST /admin/sources/<name>/health` (with admin key).
   - If 4xx: credential missing or wrong type.
   - If 5xx: upstream unreachable — escalate to L6.

   **L5 Protocol surface:**
   - **401:** `curl -I <agent-url>/v1/agent.json` — confirm `WWW-Authenticate: Bearer
     realm=...` is present (spec requirement). Then:
     `curl -H "Authorization: Bearer <admin-key>" <agent-url>/v1/agent.json` — if
     200, the key is valid and the caller is sending the wrong credential; if still
     401, check that `require_identity` is applied to the route in `src/main.py`.
   - **404:** confirm the router is `include_router`-ed via `grep -n "include_router"
     src/main.py`; a missing include_router = L3, not L5.
   - **422:** compare the request shape against the SDK's `MessageSendParams` schema;
     run `curl -X POST <agent-url>/v1/message:send -H "..." -d '{}' --verbose` to
     see the FastAPI validation error detail.
   - **SI-5 check (proactive):**
     `grep -rn 'include_router\|APIRouter' src/routes/ src/main.py 2>/dev/null` —
     confirm every router mounts with `Depends(require_identity)`; a missing
     dependency is an SI-5 violation (auth bypass).

   **L6 Upstream:**
   - Read the adapter's `allowed_hosts`. Confirm the upstream host is listed.
   - `curl -I <upstream-base-url>` to check reachability.
   - Check the adapter's `health_check()` is implemented.

   **L7 Test:**
   - Run `pytest -v <failing-test-path>` and capture the assertion failure.
   - Read the test file and the code under test. Identify the assertion and the
     actual value.

4. **State root cause** in one sentence. Example:
   "Root cause: `AlphaGeoAdapter.allowed_hosts` is empty, disabling the SSRF guard
   and causing every outbound call to be rejected (SI-7 violation)."

5. **Prescribe the fix** with the exact file, line, and change needed. Do NOT make
   the change — hand it to the team with the `/add-source` or `/add-tool` skill,
   or direct to the relevant CLAUDE.md invariant.

6. **Check if this is an SI violation.** If the root cause maps to SI-1…SI-7, flag
   it as a security invariant violation (Critical or High severity) and recommend
   `/codify` to make it a permanent LRN check.

## Report format

```
## Diagnosis — <agent-name>
Symptom:     <described symptom>
Layer:       L<N> — <layer name>
Root cause:  <one sentence>

Fix:
  File:    <src/path/file.py>:<line>
  Change:  <description of the change>
  Skill:   </add-source | /add-tool | manual edit>

SI violation: YES (SI-<N>) — recommend /codify | NO

Next: apply fix → pytest -q tests/ → /agent-verify
```

## Rules

- Advisory only — never edit files.
- If the symptom is ambiguous across two layers, probe both and report which
  layer the evidence supports.
- If the agent isn't running, offer to boot it for the duration of the triage
  (`DEV_MODE=true`) and kill it when done. Before booting, check the port is free:
  `lsof -i :<port> -t` — if a PID is returned, ask whether to use it instead.
- Never echo credential values, tokens, or `MASTER_KEY` — reference by field name
  and presence/absence only.
