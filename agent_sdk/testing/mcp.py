"""MCP client helper and Phase 1.5 tools gate for acceptance runs (GH-209).

PROVISIONAL (``agent_sdk.testing``).  ``McpClient`` speaks the MCP
Streamable HTTP JSON-RPC subset the gate needs: ``initialize``, paginated
``tools/list``, ``tools/call``, and (GH-205) paginated ``prompts/list`` and
``prompts/get``.  ``McpTestClient`` is an alias of ``McpClient``.  ``run_gate`` checks the tool list, then
calls each read-only tier-1 tool once with its ``sample=`` arguments.

Security: the bearer is read from ``key_file`` only (there is no key argument,
and no env var or argv path).  Errors and gate output carry tool names and
``sample=`` args only, never headers, tokens, or raw ``tools/call`` bodies.

CLI::

    python -m agent_sdk.testing.mcp --base-url URL --key-file PATH \
        --samples-file samples.json [--expected-count N] [--size-budget BYTES] \
        [--allow-error TOOL]... [--opt-in TOOL]...

``samples.json`` maps tool name to its ``sample=`` args (or ``null``).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import httpx

from ..routes.mcp import MCP_INTERRUPT_SUFFIX

PROTOCOL_VERSION = "2025-11-25"
DEFAULT_SIZE_BUDGET = 120_000
_MAX_PAGES = 100


class McpError(Exception):
    """Transport or protocol failure; the message is fixed text (SI-2)."""


class McpClient:
    def __init__(
        self,
        base_url: str,
        *,
        key_file: str | Path,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 60.0,
    ) -> None:
        token = Path(key_file).read_text().strip()
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            transport=transport,
            timeout=timeout,
        )
        self._next_id = 0
        self._session: str | None = None

    async def __aenter__(self) -> McpClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self._http.aclose()

    async def _post(self, body: dict[str, Any]) -> httpx.Response:
        headers = {"Accept": "application/json, text/event-stream"}
        if self._session:
            headers["Mcp-Session-Id"] = self._session
        try:
            resp = await self._http.post("/mcp", json=body, headers=headers)
        except httpx.TransportError:
            raise McpError("mcp transport error") from None
        if resp.status_code >= 400:
            raise McpError(f"mcp http error {resp.status_code}")
        return resp

    async def _rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._next_id += 1
        body: dict[str, Any] = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        if params is not None:
            body["params"] = params
        resp = await self._post(body)
        sid = resp.headers.get("Mcp-Session-Id")
        if sid:
            self._session = sid
        try:
            if "text/event-stream" in resp.headers.get("content-type", ""):
                lines = [ln[5:].strip() for ln in resp.text.splitlines() if ln.startswith("data:")]
                msg = json.loads(lines[-1])
            else:
                msg = resp.json()
        except (ValueError, IndexError):
            raise McpError("mcp response is not valid JSON-RPC") from None
        if not isinstance(msg, dict) or "error" in msg or not isinstance(msg.get("result"), dict):
            raise McpError("mcp JSON-RPC error")
        return msg["result"]

    async def initialize(self) -> dict[str, Any]:
        result = await self._rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "agent-sdk-acceptance", "version": "1"},
            },
        )
        await self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return result

    async def list_tools(self) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(_MAX_PAGES):
            result = await self._rpc("tools/list", {"cursor": cursor} if cursor else {})
            tools.extend(result.get("tools") or [])
            cursor = result.get("nextCursor")
            if not cursor:
                return tools
        raise McpError("mcp tools/list pagination did not end")

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return await self._rpc("tools/call", {"name": name, "arguments": arguments})

    async def list_prompts(self) -> list[dict[str, Any]]:
        prompts: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(_MAX_PAGES):
            result = await self._rpc("prompts/list", {"cursor": cursor} if cursor else {})
            prompts.extend(result.get("prompts") or [])
            cursor = result.get("nextCursor")
            if not cursor:
                return prompts
        raise McpError("mcp prompts/list pagination did not end")

    async def get_prompt(self, name: str) -> dict[str, Any]:
        return await self._rpc("prompts/get", {"name": name})


McpTestClient = McpClient


@dataclass
class GateResult:
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    called: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


def _has_ref(node: Any) -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k in ("$ref", "$defs"):
                found.append(k)
            found.extend(_has_ref(v))
    elif isinstance(node, list):
        for v in node:
            found.extend(_has_ref(v))
    return found


def _check_list(tools: list[dict[str, Any]], expected_count: int | None, size_budget: int) -> list[str]:
    out: list[str] = []
    counted = sum(1 for t in tools if t.get("name") != "load_skill")
    if expected_count is not None and counted != expected_count:
        out.append(f"tools/list count {counted} != registered tier-1 tools {expected_count}")
    for t in tools:
        name = t.get("name", "?")
        props = (t.get("inputSchema") or {}).get("properties") or {}
        for pname, pschema in props.items():
            if not (isinstance(pschema, dict) and str(pschema.get("description") or "").strip()):
                out.append(f"tool {name}: input field {pname} has no description")
        for key in sorted(set(_has_ref(t.get("inputSchema")))):
            out.append(f"tool {name}: inputSchema contains {key}")
    size = len(json.dumps(tools, separators=(",", ":")).encode())
    if size > size_budget:
        out.append(f"tools/list size {size} bytes exceeds budget {size_budget}")
    return out


def _is_interrupt(result: dict[str, Any]) -> bool:
    content = result.get("content")
    if not (result.get("isError") is True and isinstance(content, list) and content):
        return False
    first = content[0]
    text = first.get("text") if isinstance(first, dict) else None
    return isinstance(text, str) and text.endswith(MCP_INTERRUPT_SUFFIX)


async def run_gate(
    client: McpClient,
    samples: dict[str, dict[str, Any] | None],
    *,
    expected_count: int | None = None,
    size_budget: int = DEFAULT_SIZE_BUDGET,
    allow_errors: Iterable[str] = (),
    opt_in: Iterable[str] = (),
) -> GateResult:
    allow, opted = set(allow_errors), set(opt_in)
    result = GateResult()
    tools = await client.list_tools()
    result.failures.extend(_check_list(tools, expected_count, size_budget))
    if result.failures:
        return result
    for t in tools:
        name = t["name"]
        args = samples.get(name)
        if args is None:
            result.warnings.append(f"tool {name}: no sample=, skipped")
            continue
        read_only = (t.get("annotations") or {}).get("readOnlyHint") is True
        if not read_only and name not in opted:
            result.warnings.append(f"tool {name}: not read_only (no readOnlyHint), skipped; opt in to call it")
            continue
        call = await client.call_tool(name, args)
        result.called.append(name)
        if call.get("isError") is not True:
            continue
        shown = f"tool {name} args {json.dumps(args, sort_keys=True)}"
        if _is_interrupt(call):
            result.warnings.append(f"{shown}: needs user input, skipped")
        elif name in allow:
            result.warnings.append(f"{shown}: isError on allow-list")
        else:
            result.failures.append(f"{shown}: tools/call returned isError")
            return result
    return result


async def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m agent_sdk.testing.mcp")
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--key-file", required=True)
    ap.add_argument("--samples-file", required=True)
    ap.add_argument("--expected-count", type=int)
    ap.add_argument("--size-budget", type=int, default=DEFAULT_SIZE_BUDGET)
    ap.add_argument("--allow-error", action="append", default=[])
    ap.add_argument("--opt-in", action="append", default=[])
    a = ap.parse_args(argv)
    samples = json.loads(Path(a.samples_file).read_text())
    try:
        async with McpClient(a.base_url, key_file=a.key_file) as client:
            await client.initialize()
            res = await run_gate(
                client,
                samples,
                expected_count=a.expected_count,
                size_budget=a.size_budget,
                allow_errors=a.allow_error,
                opt_in=a.opt_in,
            )
    except McpError as exc:
        print(f"FAIL: {exc}")
        return 1
    for w in res.warnings:
        print(f"WARN: {w}")
    for f in res.failures:
        print(f"FAIL: {f}")
    print(f"{'PASS' if res.ok else 'FAIL'}: {len(res.called)} tools called")
    return 0 if res.ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
