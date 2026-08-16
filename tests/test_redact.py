"""C-007 safe_error_text: control/line-break neutralisation shared between
loop.py's SI-2 log-injection guard and content_types.py's GH-130/RT-004
delimiter-safety sanitiser (workspace/components/README.md, C-007).

Also covers C-016 safe_block_text directly (RT-014) — previously exercised
only indirectly through MarketBriefing in tests/test_content_types.py."""

from __future__ import annotations

import logging

import pytest

from agent_sdk.common.redact import (
    frame_locations,
    safe_block_text,
    safe_cell_text,
    safe_error_text,
)

_LINE_SEPARATOR = chr(0x2028)
_PARAGRAPH_SEPARATOR = chr(0x2029)


@pytest.mark.parametrize(
    "char",
    ["\n", "\r", "\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", _LINE_SEPARATOR, _PARAGRAPH_SEPARATOR],
)
def test_safe_error_text_neutralizes_every_splitlines_break_char(char: str) -> None:
    """Every character str.splitlines() treats as a line break must become a
    space — a filter that only handles \\r/\\n is bypassable (RT-004)."""
    result = safe_error_text(f"before{char}after", max_len=None)
    assert result.splitlines() == [result]
    assert char not in result


def test_safe_error_text_neutralizes_ansi_escape() -> None:
    result = safe_error_text("\x1b[31mred\x1b[0m", max_len=None)
    assert "\x1b" not in result


def test_safe_error_text_neutralizes_c1_controls() -> None:
    result = safe_error_text("a\x9bb", max_len=None)
    assert "\x9b" not in result


def test_safe_error_text_truncates_by_default() -> None:
    assert len(safe_error_text("x" * 100)) == 64


def test_safe_error_text_max_len_none_preserves_full_length() -> None:
    long_value = "y" * 200
    assert safe_error_text(long_value, max_len=None) == long_value


def test_safe_error_text_strips_leading_and_trailing_whitespace() -> None:
    assert safe_error_text("  padded  ", max_len=None) == "padded"


# RT-010: safe_cell_text()'s compact-separator exemption. The original rule —
# neutralise a spaced separator (":", ",", "@", "–", "—", "→") only when it sits
# next to whitespace or a value boundary — left a real gap: "a,b" has neither
# side spaced, so its comma survived untouched, and a category-key value
# shaped like "a,b" rendered as two categories where the true count was one
# (tests/test_content_types.py::
# test_multi_category_chart_compact_category_key_comma_does_not_fabricate_pair
# reproduces the fabricated-boundary render end to end).
#
# ",", ":", "–", "—", "→" now survive compact ONLY when flanked by a digit on
# both sides — the shape of a genuine numeric literal, range, or timestamp —
# and are neutralised in every other compact position. "@" is the sole
# remaining, deliberately documented exception: its overwhelmingly common
# compact use is a real email address, flanked by letters rather than digits,
# so it keeps the original whitespace-adjacency rule (redact.py's module
# comment carries the full rationale).


@pytest.mark.parametrize("sep", [",", ":", "–", "—", "→"])
def test_safe_cell_text_neutralizes_compact_separator_between_letters(sep: str) -> None:
    result = safe_cell_text(f"a{sep}b")
    assert sep not in result


@pytest.mark.parametrize("sep", [",", ":", "–", "—", "→"])
def test_safe_cell_text_preserves_compact_separator_between_digits(sep: str) -> None:
    assert safe_cell_text(f"1{sep}2") == f"1{sep}2"


def test_safe_cell_text_preserves_thousands_separator() -> None:
    assert safe_cell_text("1,234") == "1,234"


def test_safe_cell_text_preserves_iso_time_of_day() -> None:
    assert safe_cell_text("09:30:00Z") == "09:30:00Z"


def test_safe_cell_text_neutralizes_compact_separator_at_string_boundary() -> None:
    """A compact separator with no character on one side (start/end of the
    value) is not digit-flanked either, so it stays neutralised — the same
    outcome the old whitespace-boundary rule already gave it."""
    assert safe_cell_text(",tail") == "，tail"
    assert safe_cell_text("head,") == "head，"


def test_safe_cell_text_preserves_compact_email() -> None:
    """The documented residual: "@" keeps its old, narrower whitespace-
    adjacency rule rather than the digit-flank rule, because its legitimate
    compact use (an email address) is letter-flanked, not digit-flanked. A
    digit-flank rule here would mangle every real email in every render."""
    assert safe_cell_text("alice@corp.com") == "alice@corp.com"


def test_safe_cell_text_compact_at_between_letters_is_an_accepted_residual() -> None:
    """Documents the residual rather than asserting a fix (RT-010): a compact
    "@" between letters is indistinguishable, at the value level, from a real
    email address, so it is deliberately NOT neutralised. A field whose own
    contract is never an email (e.g. a location name) is not protected from a
    hostile compact "@" — closing that would require field-level type
    information safe_cell_text does not have."""
    assert "@" in safe_cell_text("Room@Building")


# RT-014: safe_block_text() — the block-text counterpart to safe_error_text
# (C-016), for fields whose contract is a multi-line markdown document.
# Previously exercised only indirectly through MarketBriefing in
# tests/test_content_types.py; these tests pin the helper's own contract.


def test_safe_block_text_preserves_newline_tab_and_pipe() -> None:
    """\\n, \\t and | are legitimate markdown content here, not structure —
    the opposite choice from safe_error_text's single-line delimited cells."""
    result = safe_block_text("heading\n\tindented | cell\nnext line")
    assert result == "heading\n\tindented | cell\nnext line"


def test_safe_block_text_normalizes_crlf_to_lf() -> None:
    assert safe_block_text("a\r\nb\r\nc") == "a\nb\nc"


def test_safe_block_text_normalizes_bare_cr_to_lf() -> None:
    """A bare CR rewrites the current terminal line (log-injection); it must
    normalise to \\n rather than surviving or being merely stripped."""
    assert safe_block_text("a\rb") == "a\nb"


@pytest.mark.parametrize(
    "char",
    ["\x1b", "\x9b", "\x85", "\x00", _LINE_SEPARATOR, _PARAGRAPH_SEPARATOR],
    ids=["ESC", "CSI", "NEL", "NUL", "LINE_SEPARATOR", "PARAGRAPH_SEPARATOR"],
)
def test_safe_block_text_neutralizes_escape_and_control_chars(char: str) -> None:
    """ANSI/terminal escape introducers and the rest of C0/DEL/C1 must still
    collapse to a space, even though \\n/\\t survive (SI-2 holds)."""
    result = safe_block_text(f"before{char}after")
    assert char not in result
    assert result == "before after"


# RT-004: frame_locations() — shared by every generic ``except Exception``
# catch-all on a tool-dispatch surface (routes/mcp.py, routes/admin.py,
# agent/loop.py) so the "at parity" claims in those branches' comments and
# in LRN-044's Check clause hold against the actual landed code.


def _raise(depth: int) -> None:
    if depth <= 0:
        raise ValueError("boom")
    _raise(depth - 1)


def test_frame_locations_formats_filename_colon_lineno() -> None:
    try:
        _raise(2)
    except ValueError as exc:
        result = frame_locations(exc)
    for entry in result.split("|"):
        filename, _, lineno = entry.rpartition(":")
        assert filename, result
        assert lineno.isdigit(), result


def test_frame_locations_includes_own_raise_site() -> None:
    try:
        _raise(0)
    except ValueError as exc:
        result = frame_locations(exc)
    assert __file__ in result


def test_frame_locations_caps_at_limit() -> None:
    try:
        _raise(10)
    except ValueError as exc:
        result = frame_locations(exc, limit=3)
    assert len(result.split("|")) == 3


def test_frame_locations_excludes_source_line_text() -> None:
    try:
        raise ValueError("SECRET_boom")
    except ValueError as exc:
        result = frame_locations(exc)
    assert "SECRET_boom" not in result
    assert "raise ValueError" not in result


# ── C-017 diagnosability parity across the two model clients ────────────────
#
# BedrockModelClient logged the exception type + frame_locations() in its
# generic catch-all while OpenAIModelClient logged nothing at all, so an
# upstream failure was diagnosable on one backend and silent on the other.
# The re-raised ModuleNotFoundError had the same shape of problem: loop.py
# catches only AgentError around converse(), so it reaches runner.py's
# catch-all and becomes a bare "internal error" with no log record anywhere.


def _make_failing_client(monkeypatch, backend, exc):
    """Drive a model client's converse() to the given failure."""
    import asyncio

    if backend == "openai":
        from agent_sdk.agent.openai_client import OpenAIModelClient

        client = OpenAIModelClient(model="gpt-5", api_key="k")

        class _Chat:
            class completions:
                @staticmethod
                async def create(**_kwargs):
                    raise exc

        class _Fake:
            chat = _Chat()

        client._client = _Fake()
    else:
        from agent_sdk.agent.bedrock import BedrockModelClient

        client = BedrockModelClient(region="us-east-1", model_arn="arn:aws:x")

        class _Boto:
            @staticmethod
            def converse(**_kwargs):
                raise exc

        client._client = _Boto()

    async def _run():
        return await client.converse(system="s", messages=[], tools=[])

    return _run


_BACKEND_LOGGER = {
    "bedrock": "agent_sdk.agent.bedrock",
    "openai": "agent_sdk.agent.openai_client",
}


@pytest.mark.parametrize("backend", ["bedrock", "openai"])
def test_both_model_clients_log_frame_locations(monkeypatch, sdk_caplog, backend):
    """Parity: a generic upstream failure must leave a diagnosable log record
    naming the exception type and frame locations on BOTH backends, while the
    wire-facing AgentError message stays generic.

    Uses ``sdk_caplog`` (tests/conftest.py), not plain ``caplog``: once any
    test in the session builds an app, ``configure_logging()`` sets
    ``propagate = False`` on the ``agent_sdk`` root logger, so records from
    ``agent_sdk.agent.bedrock``/``agent_sdk.agent.openai_client`` stop
    reaching the stdlib root logger that ``caplog`` attaches to.
    """
    import asyncio

    if backend == "openai":
        pytest.importorskip("openai", reason="optional extra; static parity checked below")

    from agent_sdk.models.errors import AgentError

    run = _make_failing_client(monkeypatch, backend, RuntimeError("vendor detail"))
    with sdk_caplog(_BACKEND_LOGGER[backend], logging.ERROR) as records:
        with pytest.raises(AgentError) as excinfo:
            asyncio.run(run())

    assert excinfo.value.message == "model invocation failed"
    joined = " ".join(r.getMessage() for r in records)
    assert "RuntimeError" in joined, f"{backend}: exception type not logged: {joined!r}"
    assert "frames=" in joined, f"{backend}: frame_locations not logged: {joined!r}"
    # SI-2: vendor-response detail must never reach the log line
    assert "vendor detail" not in joined


_MODEL_CLIENTS = {
    "agent_sdk.agent.bedrock": "botocore",
    "agent_sdk.agent.openai_client": "openai",
}


def _converse_try_block(module_name: str):
    """The ast.Try node wrapping the model call in a client's converse()."""
    import ast
    import importlib
    import inspect

    module = importlib.import_module(module_name)
    tree = ast.parse(inspect.getsource(module))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "converse":
            tries = [n for n in node.body if isinstance(n, ast.Try)]
            assert tries, f"{module_name}: converse() has no try block"
            return tries[-1]
    raise AssertionError(f"{module_name}: no converse() found")


@pytest.mark.parametrize("module_name", sorted(_MODEL_CLIENTS))
def test_deferred_backend_import_is_inside_the_guarded_block(module_name):
    """The deferred backend import must sit INSIDE converse()'s try.

    When the optional extra is genuinely absent, that import is the statement
    that raises ModuleNotFoundError. Placed above the try — as it originally
    was — the except ModuleNotFoundError branch is unreachable in precisely
    the situation it was written for, and the failure reaches runner.py's
    catch-all as an unlogged bare "internal error"."""
    import ast

    expected = _MODEL_CLIENTS[module_name]
    try_node = _converse_try_block(module_name)
    imported: list[str] = []
    for stmt in try_node.body:
        if isinstance(stmt, ast.Import):
            imported += [alias.name for alias in stmt.names]
        elif isinstance(stmt, ast.ImportFrom) and stmt.module:
            imported.append(stmt.module)

    assert any(name.split(".")[0] == expected for name in imported), (
        f"{module_name}: converse() does not import {expected!r} inside its "
        f"try block (found {imported}). The ModuleNotFoundError handler is "
        "unreachable when the extra is missing."
    )


@pytest.mark.parametrize("module_name", sorted(_MODEL_CLIENTS))
def test_module_not_found_handler_logs_before_reraising(module_name):
    """Re-raising unwrapped is only half the contract — nothing downstream
    logs it, so the handler itself must."""
    import ast

    for handler in _converse_try_block(module_name).handlers:
        names = {
            n.id for n in ast.walk(handler.type) if isinstance(n, ast.Name)
        } if handler.type else set()
        if "ModuleNotFoundError" not in names:
            continue
        calls = [n for n in ast.walk(handler) if isinstance(n, ast.Call)]
        assert any(
            isinstance(c.func, ast.Attribute) and c.func.attr in ("error", "warning")
            for c in calls
        ), f"{module_name}: ModuleNotFoundError handler re-raises without logging"
        return
    raise AssertionError(f"{module_name}: no ModuleNotFoundError handler in converse()")


@pytest.mark.parametrize("module_name", sorted(_MODEL_CLIENTS))
def test_generic_catch_all_is_diagnosable(module_name):
    """C-017 parity: the generic `except Exception` in each model client must
    log (directly or via a _log_* helper) rather than wrap silently. Enforced
    structurally so it still holds where the optional extra is not installed
    and the behavioural test skips."""
    import ast

    for handler in _converse_try_block(module_name).handlers:
        names = {
            n.id for n in ast.walk(handler.type) if isinstance(n, ast.Name)
        } if handler.type else {"Exception"}
        if "Exception" not in names:
            continue
        referenced = {n.id for n in ast.walk(handler) if isinstance(n, ast.Name)}
        referenced |= {
            n.attr for n in ast.walk(handler) if isinstance(n, ast.Attribute)
        }
        assert "frame_locations" in referenced or any(
            r.startswith("_log") for r in referenced
        ), (
            f"{module_name}: generic `except Exception` neither logs "
            "frame_locations() nor delegates to a _log_* helper — an upstream "
            "failure would be undiagnosable from server logs."
        )
        return
    raise AssertionError(f"{module_name}: no generic `except Exception` in converse()")


@pytest.mark.parametrize("backend", ["bedrock", "openai"])
def test_missing_backend_module_leaves_an_install_hint(sdk_caplog, backend):
    """A missing optional extra is re-raised unwrapped so it is not relabelled
    as an upstream error — but re-raising ALONE loses it, because nothing
    between converse() and runner.py's catch-all logs it (runner.py has no
    logger). The hint must reach a log record.

    Note the deferred `import` must sit INSIDE converse()'s try block: when the
    extra is genuinely absent, that import is what raises, so an import placed
    above the try makes this branch unreachable in the one case it exists for.

    Uses ``sdk_caplog`` (tests/conftest.py), not plain ``caplog`` — see the
    docstring on ``test_both_model_clients_log_frame_locations`` above.
    """
    import asyncio

    run = _make_failing_client(
        None, backend, ModuleNotFoundError("No module named 'awscrt'")
    )
    with sdk_caplog(_BACKEND_LOGGER[backend], logging.ERROR) as records:
        with pytest.raises(ModuleNotFoundError):
            asyncio.run(run())

    joined = " ".join(r.getMessage() for r in records)
    # Either the injected failure or, where the extra is genuinely absent, the
    # real import failure — both must surface the missing module name.
    assert "No module named" in joined, (
        f"{backend}: the install hint was swallowed — re-raising without "
        f"logging leaves runner.py to report a bare 'internal error'. "
        f"Got: {joined!r}"
    )
