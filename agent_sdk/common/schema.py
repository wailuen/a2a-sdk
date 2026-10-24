"""JSON Schema helpers for MCP ``tools/list`` (C-060, GH-206, GH-221).

Only schema positions are walked, so a property *named* ``title`` or
``default`` and data keywords (``default``, ``enum``, ``examples``) survive.
"""

from __future__ import annotations

from typing import Any

_SCHEMA_MAPS = ("properties", "$defs", "definitions", "patternProperties")
_SCHEMA_NODES = ("items", "additionalProperties", "not", "if", "then", "else", "contains", "propertyNames")
_SCHEMA_LISTS = ("anyOf", "oneOf", "allOf", "prefixItems")
_REF_PREFIX = "#/$defs/"
_NULL = {"type": "null"}


def strip_schema_titles(node: Any) -> Any:
    """GH-221: copy of a JSON Schema without pydantic's auto-generated
    ``title`` keys."""
    if not isinstance(node, dict):
        return node
    out: dict[str, Any] = {}
    for key, value in node.items():
        if key == "title" and isinstance(value, str):
            continue
        if key in _SCHEMA_MAPS and isinstance(value, dict):
            out[key] = {k: strip_schema_titles(v) for k, v in value.items()}
        elif key in _SCHEMA_NODES:
            out[key] = strip_schema_titles(value)
        elif key in _SCHEMA_LISTS and isinstance(value, list):
            out[key] = [strip_schema_titles(v) for v in value]
        else:
            out[key] = value
    return out


def _nullable_inner(node: Any) -> dict[str, Any] | None:
    """The ``X`` of ``anyOf: [X, {"type": "null"}]`` (either order), else None."""
    if not isinstance(node, dict):
        return None
    options = node.get("anyOf")
    if not isinstance(options, list) or len(options) != 2:
        return None
    nulls = [o for o in options if o == _NULL]
    others = [o for o in options if o != _NULL]
    if len(nulls) != 1 or len(others) != 1 or not isinstance(others[0], dict):
        return None
    return others[0]


def _nullable_members(node: Any) -> list[dict[str, Any]] | None:
    """GH-236: the non-null members of an ``anyOf`` of 3+ members that holds
    exactly one ``{"type": "null"}``, else None."""
    if not isinstance(node, dict):
        return None
    options = node.get("anyOf")
    if not isinstance(options, list) or len(options) < 3:
        return None
    others = [o for o in options if o != _NULL]
    if len(options) - len(others) != 1 or not all(isinstance(o, dict) for o in others):
        return None
    return others


class _Flattener:
    def __init__(self, defs: dict[str, Any], keep_required: bool) -> None:
        self.defs = defs
        self.keep_required = keep_required
        self.kept: set[str] = set()

    def _resolve(self, node: Any) -> Any:
        seen: set[str] = set()
        while isinstance(node, dict):
            ref = node.get("$ref")
            if not isinstance(ref, str) or not ref.startswith(_REF_PREFIX):
                break
            name = ref[len(_REF_PREFIX) :]
            target = self.defs.get(name)
            if name in seen or not isinstance(target, dict):
                break
            seen.add(name)
            node = {**target, **{k: v for k, v in node.items() if k != "$ref"}}
        return node

    def walk(self, node: Any, stack: tuple[str, ...], at_property: bool = False, keep_null: bool = False) -> Any:
        if not isinstance(node, dict):
            return node
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith(_REF_PREFIX):
            name = ref[len(_REF_PREFIX) :]
            target = self.defs.get(name)
            if isinstance(target, dict):
                siblings = {k: v for k, v in node.items() if k != "$ref"}
                if name in stack:
                    self.kept.add(name)
                    return self._finish({"$ref": ref, **siblings}, stack, at_property, keep_null)
                merged = {**target, **siblings}
                return self.walk(merged, (*stack, name), at_property, keep_null)
        return self._finish(node, stack, at_property, keep_null)

    def _finish(
        self, node: dict[str, Any], stack: tuple[str, ...], at_property: bool, keep_null: bool = False
    ) -> dict[str, Any]:
        out: dict[str, Any] = {}
        collapsed: set[str] = set()
        for key, value in node.items():
            if key == "$defs":
                continue
            if key == "default" and value is None:
                continue
            if key == "discriminator" and isinstance(value, dict) and "mapping" in value:
                # The mapping targets are inlined, so its '#/$defs/' refs dangle.
                value = {k: v for k, v in value.items() if k != "mapping"}
            if key == "properties" and isinstance(value, dict):
                props: dict[str, Any] = {}
                required_names = node.get("required")
                if not isinstance(required_names, list):
                    required_names = []
                for pname, pval in value.items():
                    keep = False
                    resolved = self._resolve(pval)
                    if _nullable_inner(resolved) is not None or _nullable_members(resolved) is not None:
                        # Output: structuredContent is dumped with exclude_none,
                        # which drops a None key, so every nullable field leaves
                        # required. A required field with no default also stays
                        # nullable, because a custom model_serializer (e.g.
                        # TimeSeriesDataPoint.value) may re-insert it as null.
                        keep = not self.keep_required and pname in required_names and "default" not in resolved
                        collapsed.add(pname)
                    props[pname] = self.walk(pval, stack, True, keep)
                out[key] = props
            elif key in ("definitions", "patternProperties") and isinstance(value, dict):
                out[key] = {k: self.walk(v, stack) for k, v in value.items()}
            elif key in _SCHEMA_NODES:
                out[key] = self.walk(value, stack)
            elif key in _SCHEMA_LISTS and isinstance(value, list):
                out[key] = [self.walk(v, stack) for v in value]
            else:
                out[key] = value
        if collapsed and not self.keep_required and isinstance(out.get("required"), list):
            required = [r for r in out["required"] if r not in collapsed]
            if required:
                out["required"] = required
            else:
                del out["required"]
        if at_property:
            members = _nullable_members(out)
            if members is not None:
                if keep_null:
                    return out
                return {**{k: v for k, v in out.items() if k != "anyOf"}, "anyOf": members}
        inner = _nullable_inner(out) if at_property else None
        if inner is not None and keep_null:
            single = inner.get("type")
            if isinstance(single, str) and "enum" not in inner and "const" not in inner:
                siblings = {k: v for k, v in out.items() if k != "anyOf"}
                return {**inner, **siblings, "type": [single, "null"]}
            return out
        if inner is not None:
            siblings = {k: v for k, v in out.items() if k != "anyOf"}
            return {**inner, **siblings}
        return out


def flatten_schema(schema: Any, *, keep_required: bool = False) -> Any:
    """GH-206 strict mode: inline local ``#/$defs`` refs, collapse
    ``anyOf: [X, {"type": "null"}]`` to ``X`` (and drop ``null`` from an
    ``anyOf`` of 3+ members, GH-236) at property positions only
    (list items and dict values can hold ``null`` after ``exclude_none``, so
    they keep it) and drop ``default: null``. Nullable fields leave
    ``required`` (right for outputs, where ``exclude_none`` drops the key)
    unless ``keep_required`` (right for inputs, where the validator still
    demands a required-nullable key). In output mode a required nullable
    field with no default keeps ``null`` (``type: [X, "null"]``, or its
    ``anyOf`` when ``X`` has no single type), so both an omitted key and a
    serializer that re-emits ``null`` validate. A recursive model keeps its ``$ref`` and
    the ``$defs`` entries it needs. Pure: returns a copy."""
    if not isinstance(schema, dict):
        return schema
    defs = schema.get("$defs")
    flattener = _Flattener(defs if isinstance(defs, dict) else {}, keep_required)
    out = flattener.walk(schema, ())
    if flattener.kept and isinstance(out, dict):
        kept_defs: dict[str, Any] = {}
        pending = sorted(flattener.kept)
        while pending:
            name = pending.pop()
            if name in kept_defs:
                continue
            kept_defs[name] = flattener.walk(flattener.defs[name], (name,))
            pending.extend(sorted(flattener.kept - kept_defs.keys()))
        out["$defs"] = kept_defs
    return out
