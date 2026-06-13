---
id: ADR-001
title: Credential model — where every key lives
status: accepted
date: 2026-06-13
---

## Context

Agent deployments require three distinct categories of credentials:

1. **SDK API keys** — minted in the admin console; sent by callers as `Authorization: Bearer`.
2. **Upstream/vendor API keys** — keys that authenticate this agent to external APIs (CRM, financial data, Graph, etc.).
3. **LLM model-backend API keys** — keys for OpenAI, Azure OpenAI, or Anthropic.

The initial template wired category 3 via `SecretStr` fields in `Settings`, which means the keys lived in `.env`. Two problems:
- **SI-6 violation**: upstream vendor keys must never live in `.env`, argv, or logs.
- **Repeated prompting**: every new environment required the developer to re-enter the key into `.env` manually. There was no idempotency gate.

## Decision

Each category has exactly one storage location:

| Category | Storage | Access |
|---|---|---|
| SDK API key | Encrypted credential store (`__api_keys__` namespace) | Callers send it; you never read it |
| Upstream/vendor key | Encrypted credential store (source namespace, e.g. `my_source/api_token`) | `self.credential("api_token")` in the adapter |
| LLM model-backend key | Encrypted credential store (`__model__` namespace) | SDK reads at boot from `/admin → Model Backend` |
| Model routing config | `.env` (non-secret operational vars) | `Settings` fields (`OPENAI_MODEL`, `BEDROCK_MODEL_ARN`, etc.) |

**`.env` contains only operational/routing vars** — port, public URL, MASTER_KEY, Bedrock region/ARN, OpenAI model name, Azure endpoint. No secrets other than MASTER_KEY (which encrypts the store, not an upstream API key itself).

## Workflow

### First-time setup

1. `/setup` collects non-secret model backend vars (BEDROCK_MODEL_ARN, OPENAI_MODEL, AZURE_OPENAI_ENDPOINT, etc.) and writes them to `.env`. It does NOT ask for the API key.
2. `/provision` starts the agent, bootstraps the admin key, then:
   - Checks `GET /admin/api/credentials` → `response.model.fields[*].set`
   - If the LLM API key is not yet stored: prompts once, seeds via `PUT /admin/api/credentials/__model__/openai_api_key` (or `azure_openai_api_key`)
   - If already stored: skips entirely — no re-prompt

### The idempotency guarantee

Once seeded, the LLM API key is encrypted in `data/credentials.db`. On every subsequent run, `_build_model_client()` reads it from there. `/provision` checks presence before prompting — it will NEVER ask again unless you explicitly delete the store or rotate the key.

### Rotating the LLM key

```bash
# Via admin console
PUT /admin/api/credentials/__model__/openai_api_key
{"value": "sk-new-key"}

# Or via curl
curl -X PUT http://localhost:<PORT>/admin/api/credentials/__model__/openai_api_key \
  -H "Authorization: Bearer <ADMIN_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"value": "sk-new-key"}'
```

Restart the agent after rotation so `_build_model_client()` picks up the new key.

## Consequences

- **SI-6 compliant**: no LLM API key ever appears in `.env`, argv, logs, or chat output.
- **No repeated prompting**: key is seeded once per environment, stored encrypted, re-used forever.
- **Bedrock unchanged**: IAM role auth; no key required; no change to existing Bedrock deployments.
- **Custom `model_client=`**: still works — passing an explicit `ModelClient` to `Agent()` bypasses this entirely (for tests and advanced setups).
- **Breaking change**: `SecretStr` fields for LLM keys in `Settings` subclasses are now SI-6 violations. Move them to the credential store and remove the `Settings` fields.

## Anti-patterns (caught by `/redteam` — fail-closed)

```
❌  OPENAI_API_KEY=sk-...  in .env
❌  azure_openai_api_key: SecretStr in Settings
❌  os.environ["OPENAI_API_KEY"] in any tool or adapter
❌  settings.openai_api_key passed to OpenAIModelClient(api_key=...)
```

All of the above are SI-6 violations. The SDK and harness will catch them.
