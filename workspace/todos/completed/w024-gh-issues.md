# w024 — GitHub issues #86

Sourced from open issues on wailuen/a2a-sdk. All items are independent.
Run in parallel (group:G).
Target: 0.5.26.

---

- [x] `GH-86` sdk/build: emit boot warning when AGENT_NAME is the placeholder default ‖ group:G — completed 2026-06-21
  - Modifies: `agent_sdk/app.py`, `agent_sdk/config.py`, `agent_sdk/routes/agent_card.py`, `agent_sdk/routes/health.py`, `agent_sdk/routes/mcp.py`
  - Reads: `agent_sdk/app.py`, `agent_sdk/config.py`, `agent_sdk/routes/agent_card.py`, `agent_sdk/routes/health.py`, `agent_sdk/routes/mcp.py`
  - Severity: high
  - Root cause: `BaseAgentSettings` defaults `agent_name="agent"` when `AGENT_NAME` is absent from the environment. `build_agent_card()` at `routes/agent_card.py:147` silently falls back `description` to `agent_name`, producing `name:"agent"`, `description:"agent"` in the card. `build_app()` emits no warning. Downstream registries use the card for identity, display name, and task routing — a placeholder identity produces an unregisterable, un-routable agent in production with no operator signal at boot.
  - AC:
    - `build_app()` (or `BaseAgentSettings`) emits a `logger.warning()` at startup when `agent_name` equals the sentinel default `"agent"` (case-insensitive), identifying the unset `AGENT_NAME` env var as the cause
    - Outside `DEV_MODE`, the warning is escalated to a hard `ValueError` at boot so placeholder-identity agents cannot serve production traffic silently
    - Inside `DEV_MODE`, the warning is non-fatal (allows local iteration without forcing `AGENT_NAME` to be set)
    - `agent_card.py` `description` fallback: when `agent_description` is blank **and** `agent_name` is the placeholder, the card `description` field is set to `""` (empty string) rather than repeating the placeholder name — prevents the registry matching text from being "agent"
    - Unit test: boot with `AGENT_NAME` unset (default `"agent"`), `DEV_MODE=true` → warning logged, no exception
    - Unit test: boot with `AGENT_NAME` unset, `DEV_MODE=false` → `ValueError` raised at `build_app()` time
    - Unit test: boot with `AGENT_NAME="my-agent"` → no warning
  - GH: https://github.com/wailuen/a2a-sdk/issues/86
