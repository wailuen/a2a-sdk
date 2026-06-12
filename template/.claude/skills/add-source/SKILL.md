---
name: add-source
description: "Add an upstream data source to an agent-sdk agent: a SourceAdapter subclass with source_name, allowed_hosts, credential-resolved auth, url_segment'd path params, and a health_check, registered on the agent with CredentialFields, plus a test. Enforces the SSRF guard (allowed_hosts, redirects pinned), credential-store-only secrets (never env reads in adapters), and redacted errors. Use when the user wants the agent to call a new external API/upstream."
---

# /add-source — add an upstream source adapter

Every external API the agent talks to goes through a `SourceAdapter`. The base
class is the security boundary: it pins `allowed_hosts` on **every** hop (redirects
disabled by default — an allowed host redirecting elsewhere is the classic SSRF
bypass), owns timeouts + the retry-once policy, resolves credentials from the
encrypted store, and maps upstream failures to redacted `AgentError`s. Tools then
call adapter methods — they never construct an HTTP client.

Run from inside an agent repo (edits `src/sources/…`, `src/main.py`, `tests/`).
**No git commit** unless asked.

## Usage

```
/add-source [name] [--hosts <h1,h2>] [--auth bearer|api-key|oauth-cc|none]
```
- `name` — snake_case source name → `source_name` and `src/sources/<name>.py`.
- `--hosts` — the exact hostnames the adapter may reach (→ `allowed_hosts`).
- `--auth` — credential shape: `bearer` token, `api-key` header, OAuth
  client-credentials (`oauth-cc`), or `none`.

## What good looks like (the contract)

```python
# src/sources/<name>.py
from agent_sdk import SourceAdapter
from agent_sdk.validation import url_segment

class <Name>Adapter(SourceAdapter):
    source_name = "<name>"
    allowed_hosts = ["api.example.com"]          # base client refuses every other host

    @property
    def base_url(self) -> str:
        return "https://api.example.com/v1"

    def _headers(self) -> dict[str, str]:
        # resolved from THIS source's namespace in the encrypted store;
        # configured via the admin console. NEVER read an env var here.
        return {"Authorization": f"Bearer {self.credential('api_token')}"}

    async def get_<thing>(self, ident: str) -> dict:
        resp = await self.get(                    # base-class client: host-checked, retried
            f"{self.base_url}/<things>/{url_segment(ident)}",   # validated path param
            headers=self._headers(),
        )
        return resp.json()

    async def health_check(self) -> bool:
        try:
            await self.get(f"{self.base_url}/ping", headers=self._headers())
            return True
        except Exception:
            return False
```

Then register it on the agent in `src/main.py`:

```python
agent.register_source(
    <Name>Adapter,
    credentials=[
        CredentialField(name="api_token", label="<Name> API token", secret=True),
        # a URL-valued credential MUST be type="url" (SDK validates: https-only,
        # public-IP-only — no RFC1918/link-local/metadata endpoints):
        # CredentialField(name="base_url", label="Base URL", type="url"),
    ],
)
```

`register_source` is once-per-class; a duplicate class or `source_name` fails at
`build_app()`. Constructor extras go via `register_source(…, init_kwargs={…})`.

### Auth shapes

- `bearer` / `api-key` — one secret `CredentialField`; build the header in
  `_headers()` from `self.credential(...)`.
- `oauth-cc` — store `client_id` + `client_secret` (secret) as fields; fetch/cache
  the token inside the adapter (the adapter owns the token lifecycle, like retries).
  For on-behalf-of/delegated user tokens, that's `contrib.obo` territory, not a
  plain adapter — say so and stop rather than hand-rolling OBO here.
- `none` — no credentials list; still set `allowed_hosts`.

## The test (required)

Stub the HTTP layer (or the adapter method) and assert behavior without real
network. Cover at least: a happy path returns parsed data, and `health_check`
returns `True`/`False` without raising. Use the repo's `tests/conftest.py` fixtures;
never hit the live upstream in tests.

## Steps

1. Create `src/sources/<name>.py` with `source_name`, `allowed_hosts`, `_headers()`,
   the method(s) the tools need (each `url_segment()`-ing path params), `health_check`.
2. Register it in `src/main.py` with its `CredentialField`s (URL fields `type="url"`).
3. Write the test (stubbed HTTP, health check). Run `.venv/bin/python -m pytest -q`.
4. **Red-team with `sdk-advisor`** (SSRF/credential/error-redaction review of the
   adapter). Apply fixes.
5. Tell the user to add the credentials in the admin console (`/admin`) — they're
   stored encrypted; nothing goes in `.env` or code. Then `/add-tool` to expose it.

## Invariants enforced (reject the change if violated)

- **`allowed_hosts` is mandatory and exhaustive.** No wildcard hosts. If the adapter
  must follow redirects, every hop is re-checked — don't disable the check.
- **Credentials are resolved, never read.** Use `self.credential("field")` (this
  source's namespace only). Never read credential env vars in an adapter; never
  cache plaintext; never log a credential.
- **No secrets or input values in errors.** Map upstream failures to
  `AgentError(category, message, source=source_name)` with a generic message.
- **Upstream vendor keys in credential store only (SI-6).** Never write an upstream
  API key to `.env`, pass it as a CLI arg, or emit it in any log line.
- **Path params via `url_segment()`**, identifiers via `safe_id()`. Never f-string
  raw input into a URL.
- **Tools never import `httpx`.** If a tool wants a new host, it's a new/updated
  adapter — not an ad-hoc client.

## Notes

- Known residual (accepted v1): a `type="url"` credential is validated at save time,
  not at every DNS resolution (rebinding TOCTOU) — acceptable because targets are
  operator-entered, not model-controlled. Don't "fix" it per-adapter.
