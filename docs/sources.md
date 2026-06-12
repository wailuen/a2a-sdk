# Source adapters

A `SourceAdapter` owns everything about one upstream: its HTTP client,
allowed hosts, credentials, retries, and error mapping. Tools never make
raw HTTP calls.

```python
from agent_sdk import SourceAdapter
from agent_sdk.validation import url_segment

class EodhdAdapter(SourceAdapter):
    source_name = "eodhd"            # credential namespace + console label
    allowed_hosts = ["eodhd.com"]    # every request hop is checked

    async def price_history(self, symbol: str) -> dict:
        resp = await self.get(
            f"https://eodhd.com/api/eod/{url_segment(symbol)}",
            params={"api_token": self.credential("api_token")},
        )
        return resp.json()

    async def health_check(self) -> bool: ...
```

## Lifecycle

The SDK owns instantiation: one instance per registered class, constructed
at lifespan startup with `(settings, credential_resolver)` plus any
`init_kwargs` from `register_source`. Registration is once-per-class;
duplicates raise at `build_app()`. Adapters are closed (`aclose()`) at
shutdown.

```python
agent.register_source(EodhdAdapter, credentials=[
    CredentialField(name="api_token", label="EODHD API token", secret=True),
], init_kwargs={...})
```

`CredentialField` declarations drive the console's credential form;
`type="url"` fields get SSRF validation on save.

## Built-in HTTP behavior

- `self.get(...)` / `self.post(...)` / `self._request(...)`:
  - **allowed_hosts** enforced on the initial URL *and* on every hop via a
    request event hook; redirects are off by default (an allowed host
    redirecting elsewhere is an SSRF bypass) — opting in re-checks each hop.
  - timeouts (default 30s), retry-once on 429/503,
  - upstream failures mapped to redacted `AgentError`s
    (401/403 → AUTH, 429 → RATE_LIMITED, timeouts → TIMEOUT,
    other 4xx/5xx → UPSTREAM). No upstream response body ever reaches an
    error message.

## Credentials

- `self.credential("field")` resolves **only** from this source's
  namespace (`{source_name}/{field}`) in the encrypted store; missing →
  `AgentError(AUTH)` with a generic message.
- `self.credential_or_none("field")` for optional fields.
- Values are entered via the admin console and stored AES-256-GCM
  encrypted under `MASTER_KEY`. Never read credential env vars in tools or
  adapters; never log or interpolate values.

## Path parameters

Anything user-derived that lands in a URL path goes through
`agent_sdk.validation.url_segment(...)` (refuses control/separator chars
and `.`/`..`, percent-encodes the rest) or `safe_id(...)` for strict
identifiers. Never f-string raw input into a URL.
