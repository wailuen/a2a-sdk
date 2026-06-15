---
id: LRN-015
title: MCP tools/call — emits coercion failure must return isError:True, never except:pass
category: mcp
severity: high
source: GH-23 (2026-06-15)
---

# LRN-015 — MCP coercion failure must surface as `isError:True`

## Root cause

When a tool declares `emits=SomeModel` and returns a value that cannot be coerced
via `model_validate`, a bare `except: pass` let the failure through silently.
The code then returned `isError: False` with no `structuredContent` — violating
MCP §4 which requires `structuredContent` in every **successful** result when
`outputSchema` is declared. Consumers cannot distinguish this from an empty result.

## Fix (`agent_sdk/routes/mcp.py:340–349`)

Replace `except: pass` with an explicit error return:

```python
except Exception as exc:
    return {
        "content": [{"type": "text", "text": f"tool '{name}' output coercion failed: {type(exc).__name__}"}],
        "isError": True,
    }
```

Note: use `type(exc).__name__`, **not** `str(exc)` — Pydantic `ValidationError`
strings can include attacker-influenced field values, creating a prompt-injection
surface in the model context.

## Rule going forward

**Never use `except: pass` on a coercion path where `outputSchema` is declared.**
A coercion failure is a real error; surface it as `isError: True` with a
sanitized message. The success path (`isError: False` + `structuredContent`) must
only be reached when coercion actually succeeded.

This applies to any tool that declares `emits=SomeModel` and whose tool function
may return a raw dict or scalar at runtime.
