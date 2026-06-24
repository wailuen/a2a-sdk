---
id: LRN-104
category: sdk-design
severity: high
summary: deferred imports in model clients must not be silently caught by bare except Exception
prevention: (1) declare optional extras in pyproject.toml; (2) add eager import probe in build_app() for each optional backend; (3) add "except ModuleNotFoundError: raise" before bare "except Exception" in client invoke paths
---

A bare `except Exception` in a model client's `converse()` caught `ModuleNotFoundError`
and re-raised it as a generic `AgentError`, making a missing optional dependency
indistinguishable from a real upstream failure. Three-layer defense: declare the extra,
probe at startup, escape-hatch in the hot path.

## What went wrong

When an optional backend (e.g. `anthropic`, `openai`) is not installed, Python raises
`ModuleNotFoundError` at the point the deferred `import` executes — typically inside
`converse()`. A broad `except Exception` catch-all around the call silently converts
this into a generic `AgentError("upstream failure")`. The operator sees a misleading
runtime error and has no indication that a simple `pip install` extra would fix it.

## Three-layer defense

### Layer 1 — declare the extra in pyproject.toml

```toml
[project.optional-dependencies]
anthropic = ["anthropic>=0.25"]
openai    = ["openai>=1.30"]
```

This ensures `pip install agent-sdk[anthropic]` installs the dependency and that
`pip install agent-sdk` leaves it absent in a clearly documented, opt-in way.

### Layer 2 — eager import probe in build_app()

```python
# agent_sdk/app.py  (inside build_app())
if settings.model_backend == "anthropic":
    try:
        import anthropic  # noqa: F401
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "anthropic extra not installed — run: pip install agent-sdk[anthropic]"
        ) from exc
```

Failing fast at startup surfaces the missing extra before any request is processed,
with a clear actionable message.

### Layer 3 — escape-hatch in the hot path

In any model-client `converse()` that wraps a broad `except Exception`, add an
explicit re-raise guard for `ModuleNotFoundError` before the catch-all:

```python
async def converse(self, messages):
    try:
        import anthropic          # deferred import
        ...
    except ModuleNotFoundError:
        raise                     # propagate as-is — never mask install errors
    except Exception as exc:
        raise AgentError("upstream failure") from exc
```

## Check

Grep for deferred imports inside `except Exception` blocks in all model-client files:

```bash
grep -n "import " agent_sdk/clients/*.py | grep -v "^Binary"
```

Then confirm each surrounding `try/except` has an explicit `except ModuleNotFoundError: raise`
escape-hatch above any `except Exception` handler.
