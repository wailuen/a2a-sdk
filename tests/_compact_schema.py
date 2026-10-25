"""Shared parser for the compact schema strings in agent_sdk.a2ui.catalog."""
from __future__ import annotations

import re
from typing import Any

_TOKEN = re.compile(r'"[^"]*"|[{}\[\],:]|[^\s{}\[\],:"]+')


def parse_schema(text: str) -> Any:
    tokens = _TOKEN.findall(text)
    pos = 0

    def peek() -> str | None:
        return tokens[pos] if pos < len(tokens) else None

    def take() -> str:
        nonlocal pos
        tok = tokens[pos]
        pos += 1
        return tok

    def value() -> Any:
        tok = peek()
        if tok == "{":
            return obj()
        if tok == "[":
            take()
            item = value()
            while peek() == ",":
                take()
                value()
            assert take() == "]"
            return [item]
        return take()

    def obj() -> dict[str, Any]:
        assert take() == "{"
        out: dict[str, Any] = {}
        while peek() != "}":
            key = take().strip('"')
            sub: Any = None
            if peek() == ":":
                take()
                sub = value()
            if key != "...":
                out[key] = sub
            if peek() == ",":
                take()
        take()
        return out

    return value()


def required_paths(node: Any, prefix: str = "") -> set[str]:
    if isinstance(node, list):
        return required_paths(node[0], prefix + "[]")
    if not isinstance(node, dict):
        return set()
    out: set[str] = set()
    for key, sub in node.items():
        if key.endswith("?"):
            name, required = key[:-1], False
        else:
            name, required = key, True
        path = f"{prefix}.{name}" if prefix else name
        if required:
            out.add(path)
        out |= required_paths(sub, path)
    return out


def emitted_paths(value: Any, prefix: str = "") -> set[str]:
    out: set[str] = set()
    if isinstance(value, list):
        for item in value:
            out |= emitted_paths(item, prefix + "[]")
    elif isinstance(value, dict):
        for key, sub in value.items():
            path = f"{prefix}.{key}" if prefix else key
            out.add(path)
            out |= emitted_paths(sub, path)
    return out


def undeclared_paths(node: Any, value: Any, prefix: str = "") -> set[str]:
    """Reverse walk: paths in an emitted *value* that the parsed schema *node*
    does not name, recursing into nested objects and lists. A schema node that
    is a bare type (a string, ``None``) or an empty ``{}`` (an open map) is
    free-form below it."""
    if isinstance(value, list):
        if not isinstance(node, list):
            return set()
        out: set[str] = set()
        for item in value:
            out |= undeclared_paths(node[0], item, prefix + "[]")
        return out
    if not isinstance(value, dict) or not isinstance(node, dict) or not node:
        return set()
    declared = {key.rstrip("?"): sub for key, sub in node.items()}
    out = set()
    for key, sub in value.items():
        path = f"{prefix}.{key}" if prefix else key
        if key not in declared:
            out.add(path)
        else:
            out |= undeclared_paths(declared[key], sub, path)
    return out


def top_level_keys(schema: str) -> set[str]:
    """Top-level key names (optional marker stripped); empty for prose schemas."""
    if not schema.startswith("{"):
        return set()
    return {key.rstrip("?") for key in parse_schema(schema)}
