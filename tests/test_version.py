"""SI-1 — version consistency: agent_sdk.__version__ must equal pyproject.toml version."""

import tomllib
from importlib.metadata import version as _pkg_version
from pathlib import Path

import agent_sdk


def _pyproject_version() -> str:
    pyproject = Path(__file__).parent.parent / "pyproject.toml"
    with pyproject.open("rb") as fh:
        data = tomllib.load(fh)
    return data["project"]["version"]


def test_version_matches_pyproject() -> None:
    """agent_sdk.__version__ must equal the version declared in pyproject.toml."""
    assert agent_sdk.__version__ == _pyproject_version(), (
        f"agent_sdk.__version__ ({agent_sdk.__version__!r}) does not match "
        f"pyproject.toml ({_pyproject_version()!r}). "
        "Run 'python3 -m agent_sdk bump-patch' and re-install the package."
    )


def test_version_matches_installed_metadata() -> None:
    """agent_sdk.__version__ must equal what importlib.metadata reports for the installed package."""
    installed = _pkg_version("agent-sdk")
    assert agent_sdk.__version__ == installed, (
        f"agent_sdk.__version__ ({agent_sdk.__version__!r}) does not match "
        f"installed package metadata ({installed!r}). "
        "Re-install: 'pip install -e .' to sync."
    )


def test_version_is_not_hardcoded_stale() -> None:
    """Sanity-guard: the exported version must never be the old hardcoded value."""
    assert agent_sdk.__version__ != "0.4.0", (
        "__version__ reverted to the old hardcoded value '0.4.0'. "
        "The dynamic importlib.metadata read must be in place."
    )


def test_version_not_dev_in_installed_package() -> None:
    """When the package is properly installed, __version__ must not be the fallback sentinel."""
    assert agent_sdk.__version__ != "0.0.0+dev", (
        "__version__ is '0.0.0+dev', which means the package is not installed "
        "(importlib.metadata lookup failed). Run 'pip install -e .'."
    )
