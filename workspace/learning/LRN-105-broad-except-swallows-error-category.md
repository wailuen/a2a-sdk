---
id: LRN-105
category: sdk-design
severity: medium
summary: bare "except Exception" in model client invoke paths swallows distinct error categories (e.g. RateLimitError) as generic UPSTREAM
prevention: for each error type that maps to a distinct ErrorCategory, add an explicit except clause BEFORE the bare "except Exception"; order: ModuleNotFoundError → RateLimitError → other specific → Exception
---

## Body

The OpenAI client's `converse()` caught `openai.RateLimitError` with a bare
`except Exception` and re-raised it as `AgentError(UPSTREAM, "model invocation failed")`,
making a transient rate limit indistinguishable from a fatal auth failure.
`ErrorCategory.RATE_LIMITED` already existed but was not wired.

Fix: insert `except openai.RateLimitError` before `except Exception`,
raising `AgentError(RATE_LIMITED, "model rate limit exceeded; retry later")`.

General rule: every new except-clause above the bare `except Exception` must be
intentional and map to the most specific `ErrorCategory` available.

## Check

`grep -n "except Exception" agent_sdk/agent/*.py` — for every hit, verify
that no more-specific `ErrorCategory` applies to any exception the library below
can raise at that call site. If one does, an explicit clause must precede it.
