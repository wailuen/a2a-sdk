# AlphaGeo climate-risk analyst (agent-sdk port)

A worked example: the original `alphageo-mcp` server ported onto **agent-sdk**.
It answers climate-risk questions for a property or location and emits a
structured **Climate Risk Report** card over A2UI/AG-UI/MCP.

This is a reference port — it leaves the original `aihub2` server untouched and
demonstrates the SDK's domain-layer idioms end to end.

## What it shows

- **A domain A2UI card** (`src/content.py`): `ClimateRiskReport` lives in its
  own catalog `urn:alphageo:climate:v1` (the SDK's Standard Profile is frozen
  and closed to domain types). Clients that advertise the catalog render the
  card; everyone else gets the strong `to_plain_text()` fallback. Partial
  upstream failures are carried in a typed `section_errors` map.
- **A `SourceAdapter`** (`src/sources/alphageo.py`): all HTTP goes through the
  base client (host-checked on every hop). Adds per-call key auth, a 24h cache
  and 60/min throttle (both tenant-isolated by a hash of the key), and a
  Nominatim geocode fallback when AlphaGeo's geocoder 500s — with the vendor
  key never sent to Nominatim and no address/key/URL ever in an error.
- **Six tools** (`src/tools/climate.py`), all emitting the one card.
- **The OpenAI ModelClient seam** (`src/config.py`): runs on gpt-5 (vanilla or
  Azure) instead of Bedrock, behind the same `ModelClient` interface.
- **Per-call credential forwarding**: the AlphaGeo key is resolved per request
  from the encrypted store or the `X-Agent-Credentials` header. The card and
  the MCP `initialize.instructions` advertise the forwarding extension (field
  names only, never values).

## Run

```bash
cp .env.example .env          # set OPENAI_API_KEY (or Azure), MASTER_KEY, PUBLIC_URL
pip install -e .
uvicorn src.main:app --port 8045 --workers 1
```

Store an AlphaGeo key in the admin console, or have the client forward one per
request. Then point an A2A/MCP client at the agent.

## Test

```bash
pip install -e '.[dev]'
pytest
```

Tests use `agent_sdk.testing` (FakeModelClient) and a mocked HTTP transport —
no Bedrock, no OpenAI, no real AlphaGeo or Nominatim calls.
