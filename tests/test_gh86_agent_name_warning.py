"""GH-86 — build_app() emits a warning when AGENT_NAME is the placeholder default.

AC:
- DEV_MODE=true + AGENT_NAME="agent" (default) → warning logged, no exception
- DEV_MODE=false + AGENT_NAME="agent" (default) → ValueError at build_app() time
- AGENT_NAME="my-agent" (real name) → no warning
- agent_card description is "" (empty string) when agent_name is placeholder and
  agent_description is blank, not the placeholder name repeated
"""

from __future__ import annotations

import gc
import io
import logging
import sys
from contextlib import contextmanager
from typing import Generator

import pytest

from agent_sdk import BaseAgentSettings
from agent_sdk.example.agent import make_agent
from agent_sdk.testing import FakeModelClient


_SENTINEL = "agent"


@contextmanager
def capture_sdk_warnings(logger_name: str = "agent_sdk.app") -> Generator[list[str], None, None]:
    """Directly capture WARNING+ messages from a logger without relying on propagation.

    agent_sdk sets propagate=False on its root logger so pytest caplog cannot
    intercept records via the root handler.  This helper attaches a transient
    handler directly to the named logger and removes it on exit.
    """
    records: list[str] = []

    class _Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            if record.levelno >= logging.WARNING:
                records.append(record.getMessage())

    sdk_logger = logging.getLogger(logger_name)
    handler = _Collector()
    sdk_logger.addHandler(handler)
    try:
        yield records
    finally:
        sdk_logger.removeHandler(handler)


def _dev_settings(tmp_path, agent_name=_SENTINEL, **kwargs) -> BaseAgentSettings:
    return BaseAgentSettings(
        DEV_MODE=True,
        DATA_DIR=str(tmp_path / "data"),
        AGENT_NAME=agent_name,
        **kwargs,
    )


def _prod_settings(tmp_path, agent_name=_SENTINEL, **kwargs) -> BaseAgentSettings:
    return BaseAgentSettings(
        DEV_MODE=False,
        DATA_DIR=str(tmp_path / "data"),
        PUBLIC_URL="https://example.com",
        MASTER_KEY="a" * 32,
        AGENT_NAME=agent_name,
        **kwargs,
    )


def _build(settings: BaseAgentSettings):
    return make_agent(settings, model_client=FakeModelClient())


# ---------------------------------------------------------------------------
# DEV_MODE=true: warning is emitted, no exception
# ---------------------------------------------------------------------------

def test_dev_mode_placeholder_name_emits_warning(tmp_path):
    settings = _dev_settings(tmp_path)
    assert settings.agent_name == _SENTINEL

    agent = _build(settings)
    with capture_sdk_warnings() as warnings:
        app = agent.build_app()
    app.state.credential_store.close()
    gc.collect()

    assert any("AGENT_NAME" in t for t in warnings), (
        f"Expected a warning mentioning AGENT_NAME; got: {warnings}"
    )


def test_dev_mode_placeholder_name_no_exception(tmp_path):
    settings = _dev_settings(tmp_path)
    # Must not raise
    app = _build(settings).build_app()
    app.state.credential_store.close()
    gc.collect()


# ---------------------------------------------------------------------------
# DEV_MODE=false: ValueError at build_app()
# ---------------------------------------------------------------------------

def test_prod_mode_placeholder_name_raises(tmp_path):
    settings = _prod_settings(tmp_path)
    with pytest.raises(ValueError, match="AGENT_NAME"):
        _build(settings).build_app()


# ---------------------------------------------------------------------------
# Real agent_name: no warning
# ---------------------------------------------------------------------------

def test_real_agent_name_no_warning(tmp_path):
    settings = _dev_settings(tmp_path, agent_name="my-agent")
    agent = _build(settings)
    with capture_sdk_warnings() as warnings:
        app = agent.build_app()
    app.state.credential_store.close()
    gc.collect()

    placeholder_warnings = [t for t in warnings if "AGENT_NAME" in t]
    assert not placeholder_warnings, (
        f"No AGENT_NAME warning expected for real name; got: {placeholder_warnings}"
    )


# ---------------------------------------------------------------------------
# agent_card description fallback: placeholder → "" not "agent"
# ---------------------------------------------------------------------------

def test_card_description_uses_display_name_when_placeholder(tmp_path):
    settings = _dev_settings(tmp_path)
    # agent_description is blank (default ""), agent_name is "agent" (placeholder)
    # A2A §3.1: description must be non-empty — use display_name sentinel, not "".
    app = _build(settings).build_app()
    card = app.state.agent_card
    app.state.credential_store.close()
    gc.collect()

    assert card["description"] == settings.display_name, (
        f"Card description must be display_name sentinel when agent_name is placeholder; "
        f"got {card['description']!r}, expected {settings.display_name!r}"
    )
    assert card["description"].strip(), "Card description must not be blank"


def test_card_description_uses_real_name_as_fallback(tmp_path):
    """When agent_name is real and description blank, description falls back to agent_name."""
    settings = _dev_settings(tmp_path, agent_name="my-agent")
    app = _build(settings).build_app()
    card = app.state.agent_card
    app.state.credential_store.close()
    gc.collect()

    assert card["description"] == "my-agent", (
        f"Card description must fall back to agent_name when description blank; got {card['description']!r}"
    )


# ---------------------------------------------------------------------------
# RT-001: empty / whitespace-only AGENT_NAME must be treated as invalid
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("blank_name", ["", "   ", "\t", "\n"])
def test_dev_mode_empty_agent_name_emits_warning(tmp_path, blank_name):
    settings = _dev_settings(tmp_path, agent_name=blank_name)
    agent = _build(settings)
    with capture_sdk_warnings() as warnings:
        app = agent.build_app()
    app.state.credential_store.close()
    gc.collect()

    assert any("AGENT_NAME" in t for t in warnings), (
        f"Expected a warning mentioning AGENT_NAME for blank name {blank_name!r}; got: {warnings}"
    )


@pytest.mark.parametrize("blank_name", ["", "   ", "\t"])
def test_prod_mode_empty_agent_name_raises(tmp_path, blank_name):
    settings = _prod_settings(tmp_path, agent_name=blank_name)
    with pytest.raises(ValueError, match="AGENT_NAME"):
        _build(settings).build_app()


# ---------------------------------------------------------------------------
# RT-005: blank/whitespace agent_name must yield description="" (same as placeholder)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# RT-003: whitespace-padded placeholder names must be treated as placeholder
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("padded_name", ["agent ", " agent", "  agent"])
def test_dev_mode_padded_placeholder_name_emits_warning(tmp_path, padded_name):
    settings = _dev_settings(tmp_path, agent_name=padded_name)
    agent = _build(settings)
    with capture_sdk_warnings() as warnings:
        app = agent.build_app()
    app.state.credential_store.close()
    gc.collect()

    assert any("AGENT_NAME" in t for t in warnings), (
        f"Expected a warning mentioning AGENT_NAME for padded placeholder {padded_name!r}; got: {warnings}"
    )


@pytest.mark.parametrize("padded_name", ["agent ", " agent", "  agent"])
def test_prod_mode_padded_placeholder_name_raises(tmp_path, padded_name):
    settings = _prod_settings(tmp_path, agent_name=padded_name)
    with pytest.raises(ValueError, match="AGENT_NAME"):
        _build(settings).build_app()


@pytest.mark.parametrize("padded_name", ["agent ", " agent", "  agent"])
def test_card_description_uses_display_name_for_padded_placeholder(tmp_path, padded_name):
    from agent_sdk.routes.agent_card import build_agent_card
    from agent_sdk.agent.registry import ToolRegistry

    settings = _dev_settings(tmp_path, agent_name=padded_name)
    registry = ToolRegistry([], {})
    card = build_agent_card(settings, registry)

    assert card["description"] == settings.display_name, (
        f"Card description must be display_name sentinel for padded placeholder {padded_name!r}; "
        f"got {card['description']!r}, expected {settings.display_name!r}"
    )
    assert card["description"].strip(), "Card description must not be blank"


@pytest.mark.parametrize("blank_name", ["   ", "\t"])
def test_card_description_uses_display_name_for_blank_name(tmp_path, blank_name):
    """build_agent_card() must treat blank/whitespace agent_name identically to
    the placeholder: use display_name sentinel, never emit the raw whitespace."""
    from agent_sdk.routes.agent_card import build_agent_card
    from agent_sdk.agent.registry import ToolRegistry

    settings = _dev_settings(tmp_path, agent_name=blank_name)
    registry = ToolRegistry([], {})
    card = build_agent_card(settings, registry)

    assert card["description"] == settings.display_name, (
        f"Card description must be display_name for blank agent_name {blank_name!r}; "
        f"got {card['description']!r}, expected {settings.display_name!r}"
    )
    assert card["description"].strip(), "Card description must not be blank"


# ---------------------------------------------------------------------------
# RT-001: agent card 'name' (REQUIRED A2A identity field) must be normalized via
# display_name — never the raw placeholder, blank, or whitespace AGENT_NAME.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_name", [_SENTINEL, "agent", "AGENT", " agent ", "", "   ", "\t", "\n"])
def test_card_name_normalized_for_placeholder_or_blank(tmp_path, bad_name):
    from agent_sdk.routes.agent_card import build_agent_card
    from agent_sdk.agent.registry import ToolRegistry

    settings = _dev_settings(tmp_path, agent_name=bad_name)
    card = build_agent_card(settings, ToolRegistry([], {}))

    assert card["name"].strip(), (
        f"Card name must not be blank/whitespace for AGENT_NAME={bad_name!r}; "
        f"got {card['name']!r}"
    )
    assert card["name"].strip().lower() != _SENTINEL, (
        f"Card name must not expose the raw placeholder for AGENT_NAME={bad_name!r}; "
        f"got {card['name']!r}"
    )
    # All placeholder/blank inputs collapse to the same neutral sentinel as
    # display_name, matching MCP serverInfo and /health.
    assert card["name"] == settings.display_name


def test_card_name_passes_through_real_name(tmp_path):
    from agent_sdk.routes.agent_card import build_agent_card
    from agent_sdk.agent.registry import ToolRegistry

    settings = _dev_settings(tmp_path, agent_name="My Real Agent")
    card = build_agent_card(settings, ToolRegistry([], {}))
    assert card["name"] == "My Real Agent"


# ---------------------------------------------------------------------------
# RT-007: 'agent' (case-insensitive) is a permanently reserved placeholder
# sentinel — there is no escape hatch when the operator explicitly sets it.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("explicit_agent_name", ["agent", "Agent", "AGENT", "aGeNt"])
def test_explicitly_set_agent_name_still_treated_as_placeholder(tmp_path, explicit_agent_name):
    """Explicitly setting AGENT_NAME=agent (any case) is treated identically to
    the unset default — it triggers the warning / ValueError and the card name
    is normalised to the neutral sentinel.  This is a documented limitation
    (RT-007): 'agent' is permanently reserved and cannot be used as a real name.
    """
    from agent_sdk.routes.agent_card import build_agent_card
    from agent_sdk.agent.registry import ToolRegistry

    settings = _dev_settings(tmp_path, agent_name=explicit_agent_name)
    assert settings.is_placeholder_name, (
        f"is_placeholder_name must be True for explicitly-set {explicit_agent_name!r}"
    )
    assert settings.display_name == "agent-sdk-agent", (
        f"display_name must normalise explicitly-set {explicit_agent_name!r} to sentinel"
    )
    card = build_agent_card(settings, ToolRegistry([], {}))
    assert card["name"] == "agent-sdk-agent", (
        f"card name must be normalised for explicitly-set {explicit_agent_name!r}"
    )
    assert card["description"] == settings.display_name, (
        f"card description must be display_name sentinel for explicitly-set {explicit_agent_name!r}; "
        f"got {card['description']!r}, expected {settings.display_name!r}"
    )
    assert card["description"].strip(), "card description must not be blank"


# ---------------------------------------------------------------------------
# RT-003: warning message must not falsely assert cause ("default") when the
# same predicate is reached via multiple paths (unset vs explicitly-set-to-sentinel).
# The message must say "unset or set to the reserved placeholder" — never
# "placeholder default" — so an operator who deliberately set AGENT_NAME=agent
# is not misled into thinking the variable was unread.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("explicit_agent_name", ["agent", "Agent", "AGENT", "aGeNt"])
def test_explicitly_set_placeholder_warning_does_not_claim_default(tmp_path, explicit_agent_name):
    """When AGENT_NAME is explicitly set to the reserved sentinel (any case), the
    warning must NOT say 'placeholder default' — that wording falsely implies the
    env var was unread.  The message must use 'unset or set to the reserved
    placeholder' to cover both paths without asserting a single cause."""
    settings = _dev_settings(tmp_path, agent_name=explicit_agent_name)
    agent = _build(settings)
    with capture_sdk_warnings() as warnings:
        app = agent.build_app()
    app.state.credential_store.close()
    gc.collect()

    agent_name_warnings = [t for t in warnings if "AGENT_NAME" in t]
    assert agent_name_warnings, (
        f"Expected an AGENT_NAME warning for explicitly-set {explicit_agent_name!r}; got: {warnings}"
    )
    for msg in agent_name_warnings:
        assert "placeholder default" not in msg, (
            f"Warning must not say 'placeholder default' when AGENT_NAME={explicit_agent_name!r} "
            f"was explicitly set; got: {msg!r}"
        )
        assert "unset or set" in msg, (
            f"Warning must say 'unset or set' to cover both the unset and "
            f"explicitly-set-to-sentinel paths; got: {msg!r}"
        )


def test_unset_placeholder_warning_does_not_claim_default(tmp_path):
    """When AGENT_NAME is left at the default (unset), the warning must also use
    'unset or set to the reserved placeholder' — consistent with the explicitly-set
    path and not anchored to a single cause."""
    settings = _dev_settings(tmp_path)  # AGENT_NAME left at default "agent"
    agent = _build(settings)
    with capture_sdk_warnings() as warnings:
        app = agent.build_app()
    app.state.credential_store.close()
    gc.collect()

    agent_name_warnings = [t for t in warnings if "AGENT_NAME" in t]
    assert agent_name_warnings, (
        f"Expected an AGENT_NAME warning for default AGENT_NAME; got: {warnings}"
    )
    for msg in agent_name_warnings:
        assert "placeholder default" not in msg, (
            f"Warning must not say 'placeholder default'; got: {msg!r}"
        )
        assert "unset or set" in msg, (
            f"Warning must say 'unset or set'; got: {msg!r}"
        )


# ---------------------------------------------------------------------------
# RT-008: configure_logging() StreamHandler delivers the GH-86 AGENT_NAME warning
# via the SDK's own stderr handler installed by build_app(), not via an
# ad-hoc test-injected handler.
# ---------------------------------------------------------------------------

def test_configure_logging_stderr_handler_delivers_agent_name_warning(tmp_path):
    """build_app() calls configure_logging() before _check_agent_name(), so the
    SDK's own StreamHandler(sys.stderr) is in place when the warning fires.
    This test verifies the warning reaches stderr through that path — not through
    a test-injected handler on 'agent_sdk.app'."""
    sdk_root = logging.getLogger("agent_sdk")

    # Remove any pre-existing SDK handlers so configure_logging()'s idempotency
    # guard cannot skip installation.
    prior_handlers = [h for h in sdk_root.handlers if getattr(h, "_agent_sdk", False)]
    for h in prior_handlers:
        sdk_root.removeHandler(h)

    settings = _dev_settings(tmp_path)
    agent = _build(settings)

    captured = io.StringIO()
    original_stderr = sys.stderr
    sys.stderr = captured  # type: ignore[assignment]
    try:
        app = agent.build_app()
    finally:
        sys.stderr = original_stderr

    app.state.credential_store.close()
    gc.collect()

    # Verify configure_logging() installed its StreamHandler on the SDK root logger.
    sdk_handlers = [h for h in sdk_root.handlers if getattr(h, "_agent_sdk", False)]
    assert sdk_handlers, (
        "configure_logging() must install a StreamHandler with _agent_sdk=True "
        "on the 'agent_sdk' logger; none found after build_app()"
    )

    # Verify the warning was written to stderr via that handler.
    output = captured.getvalue()
    assert "AGENT_NAME" in output, (
        f"AGENT_NAME warning must appear in stderr output from the SDK's "
        f"configure_logging() StreamHandler; got: {output!r}"
    )
