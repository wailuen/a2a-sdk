# w011 — GitHub issues #23–#24

Sourced from open issues on wailuen/a2a-sdk. All items are independent.
Run in parallel (group:A).
Target: v0.5.2.

---

- [ ] `GH-23` mcp: structuredContent silently omitted on emits coercion failure ‖ group:A
  - Modifies: `agent_sdk/routes/mcp.py`
  - Reads: `agent_sdk/routes/mcp.py`, `tests/`
  - Severity: high
  - Root cause: `_handle_tools_call()` at lines 340–343 wraps `emits_type.model_validate(artifact)` in `except: pass`, then falls through to return `isError: False` with no `structuredContent`. MCP §4 requires `structuredContent` in every successful result when `outputSchema` is declared — silent coercion failure produces a structurally invalid response consumers cannot detect.
  - AC:
    - `except Exception: pass` at `mcp.py:342` is replaced with an explicit `isError: True` return surfacing the coercion failure message
    - Test: tool with `emits=SomeModel` returning an unconvertible plain dict → `tools/call` returns `isError: True`
    - Test: tool with `emits=SomeModel` returning a valid plain dict that coerces → `tools/call` returns `isError: False` with `structuredContent` present
  - GH: https://github.com/wailuen/a2a-sdk/issues/23

- [ ] `GH-24` mcp: no SSRF defense at SDK layer — tools fetching user-supplied URLs are unguarded ‖ group:A
  - Creates: `agent_sdk/common/http.py`, `tests/test_safe_get.py`
  - Modifies: `agent_sdk/sources.py`, `agent_sdk/credentials/fields.py`, `harness/CLAUDE.md`, `.claude/reference/sdk-security-invariants.md`
  - Reads: `agent_sdk/sources.py`, `agent_sdk/credentials/fields.py`, `agent_sdk/common/`
  - Severity: high
  - Root cause: No standalone SSRF-safe HTTP utility exists for tool authors who cannot use a `SourceAdapter`. The IP-blocking logic exists in two places (`sources.py:92–124`, `credentials/fields.py:22–50`) but is not shared. SI-1 bans bare httpx in CLAUDE.md but provides no approved escape hatch, leaving tool authors with no safe path for user-supplied URL fetching.
  - AC:
    - `agent_sdk/common/http.py` exports `async def safe_get(url, *, timeout=30.0)` that resolves hostname, blocks private/loopback/link-local/reserved/multicast addresses, raises `AgentError(ErrorCategory.VALIDATION, ...)` on blocked targets
    - Duplicate IP-block logic in `sources.py` and `credentials/fields.py` refactored to call shared `_is_private_ip()` from `agent_sdk/common/http.py`
    - `harness/CLAUDE.md` SI-1 updated to reference `safe_get` as the approved escape hatch
    - Tests: `safe_get` with valid public URL (passes), `169.254.169.254` (blocked), `192.168.1.1` (blocked), `localhost` (blocked)
    - `sdk-security-invariants.md` updated with `safe_get` grep check
  - GH: https://github.com/wailuen/a2a-sdk/issues/24
