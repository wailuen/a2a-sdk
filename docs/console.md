# Admin console

`/admin` (vanilla JS, no build step, strict CSP — no inline script, no
`unsafe-inline`). The page itself holds no data; every API call needs an
admin API key, which the browser keeps in memory.

## First run

With zero API keys in the store, boot prints a single-use bootstrap token
(15-minute TTL) to stdout. Paste it in the console (or send it as
`X-Bootstrap-Token` to `POST /admin/api/keys`) to mint the first admin
key. A restart regenerates the token and invalidates the old one.

## What it does

- **Keys** — mint/list/revoke API keys (prefix-only display).
- **Credentials** — the form is generated from each source's
  `CredentialField` declarations; values go straight into the encrypted
  store. `type="url"` fields are SSRF-validated.
- **Tools** — the registry with tiers/schemas; "Try" runs a tool with its
  declared `sample=` and renders the result (including the A2UI card).
- **Chat** — an AG-UI client for end-to-end testing: streams a run,
  renders text, tool calls, custom events and A2UI surfaces, and exercises
  the interrupt/resume flow.
- **Self-check** — runtime verification of externally-visible URLs, plus a
  list of team-mounted routes that carry no SDK auth dependency.

## Overriding the UI

`Agent(console_static_dir=...)` shadows SDK assets **file-by-file**: a
request for `/admin/static/<name>` is served from your directory if the
file exists there, else from the SDK's. Ship only the files you change.
Custom domain-card renderers hook in this way; keep the strict-CSP
contract (no inline handlers, modules only).
