"""contrib.azure_utils — require_azure_packages() guard.

Tests:
  1. Passes silently when both azure-data-tables and azure-identity are importable.
  2. Raises ImportError with the pip install hint when azure-data-tables is absent.
  3. Raises ImportError with the pip install hint when azure-identity is absent.
  4. The error message never leaks internal paths or secret values (SI-2).
"""

from __future__ import annotations

import importlib
import sys

import pytest


INSTALL_HINT = "pip install agent-sdk[azure]"


def _with_missing(package_name: str):
    """Context manager that makes *package_name* appear absent to importlib."""
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        original = sys.modules.get(package_name, ...)
        sys.modules[package_name] = None  # type: ignore[assignment]
        try:
            yield
        finally:
            if original is ...:
                sys.modules.pop(package_name, None)
            else:
                sys.modules[package_name] = original  # type: ignore[assignment]

    return _ctx()


# ── 1. happy path ──────────────────────────────────────────────────────────────

def test_passes_when_packages_present(monkeypatch):
    """No exception when both packages can be found."""
    import types

    fake_azure = types.ModuleType("azure")
    fake_azure_data = types.ModuleType("azure.data")
    fake_tables = types.ModuleType("azure.data.tables")
    fake_identity = types.ModuleType("azure.identity")

    monkeypatch.setitem(sys.modules, "azure", fake_azure)
    monkeypatch.setitem(sys.modules, "azure.data", fake_azure_data)
    monkeypatch.setitem(sys.modules, "azure.data.tables", fake_tables)
    monkeypatch.setitem(sys.modules, "azure.identity", fake_identity)

    # Re-import to pick up fresh state
    import importlib
    import agent_sdk.contrib.azure_utils as mod
    importlib.reload(mod)

    mod.require_azure_packages()  # must not raise


# ── 2. missing azure-data-tables ──────────────────────────────────────────────

def test_raises_when_data_tables_absent(monkeypatch):
    monkeypatch.setitem(sys.modules, "azure.data.tables", None)  # type: ignore[arg-type]

    import agent_sdk.contrib.azure_utils as mod
    importlib.reload(mod)

    with pytest.raises(ImportError) as exc_info:
        mod.require_azure_packages()

    assert INSTALL_HINT in str(exc_info.value)


# ── 3. missing azure-identity ─────────────────────────────────────────────────

def test_raises_when_identity_absent(monkeypatch):
    monkeypatch.setitem(sys.modules, "azure.identity", None)  # type: ignore[arg-type]

    import agent_sdk.contrib.azure_utils as mod
    importlib.reload(mod)

    with pytest.raises(ImportError) as exc_info:
        mod.require_azure_packages()

    assert INSTALL_HINT in str(exc_info.value)


# ── 4. SI-2: no secret / path leakage in error message ───────────────────────

def test_error_message_contains_only_install_hint(monkeypatch):
    monkeypatch.setitem(sys.modules, "azure.data.tables", None)  # type: ignore[arg-type]

    import agent_sdk.contrib.azure_utils as mod
    importlib.reload(mod)

    with pytest.raises(ImportError) as exc_info:
        mod.require_azure_packages()

    msg = str(exc_info.value)
    # Must contain the canonical hint
    assert INSTALL_HINT in msg
    # Must NOT contain raw filesystem paths or tracebacks
    assert "/Users/" not in msg
    assert "Traceback" not in msg
