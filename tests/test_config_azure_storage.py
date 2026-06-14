"""Tests for Azure Storage fields on BaseAgentSettings (AC: P0-03 follow-on).

Covers:
- azure_storage_connection_string is SecretStr (SI-6: not in repr/logs)
- azure_storage_account_name is an optional str
- azure_storage_table_prefix defaults to "agent"
- Setting both connection_string and account_name raises ValueError (ambiguous auth)
- Each field alone is accepted
- Custom table prefix is accepted
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from agent_sdk import BaseAgentSettings


def _dev_base(**kwargs) -> dict:
    """Return minimal kwargs for DEV_MODE (no PUBLIC_URL / MASTER_KEY required)."""
    return {"DEV_MODE": True, **kwargs}


# ---------------------------------------------------------------------------
# Field presence & types
# ---------------------------------------------------------------------------

def test_azure_storage_fields_default_none():
    cfg = BaseAgentSettings(**_dev_base())
    assert cfg.azure_storage_connection_string is None
    assert cfg.azure_storage_account_name is None
    assert cfg.azure_storage_table_prefix == "agent"


def test_connection_string_is_secret_str():
    cfg = BaseAgentSettings(
        **_dev_base(
            AZURE_STORAGE_CONNECTION_STRING="DefaultEndpointsProtocol=https;AccountName=foo;AccountKey=bar;EndpointSuffix=core.windows.net"
        )
    )
    assert isinstance(cfg.azure_storage_connection_string, SecretStr)


def test_connection_string_not_in_repr(capsys):
    cfg = BaseAgentSettings(
        **_dev_base(AZURE_STORAGE_CONNECTION_STRING="super-secret-connstr")
    )
    # SecretStr.__repr__ must NOT expose the value
    r = repr(cfg)
    assert "super-secret-connstr" not in r


def test_account_name_accepted():
    cfg = BaseAgentSettings(**_dev_base(AZURE_STORAGE_ACCOUNT_NAME="myaccount"))
    assert cfg.azure_storage_account_name == "myaccount"


def test_table_prefix_custom():
    cfg = BaseAgentSettings(**_dev_base(AZURE_STORAGE_TABLE_PREFIX="myprefix"))
    assert cfg.azure_storage_table_prefix == "myprefix"


# ---------------------------------------------------------------------------
# Ambiguous auth guard
# ---------------------------------------------------------------------------

def test_both_connection_string_and_account_name_raises():
    with pytest.raises(ValueError, match="ambiguous"):
        BaseAgentSettings(
            **_dev_base(
                AZURE_STORAGE_CONNECTION_STRING="DefaultEndpointsProtocol=https;AccountName=foo;AccountKey=bar;EndpointSuffix=core.windows.net",
                AZURE_STORAGE_ACCOUNT_NAME="myaccount",
            )
        )


def test_only_connection_string_ok():
    cfg = BaseAgentSettings(
        **_dev_base(
            AZURE_STORAGE_CONNECTION_STRING="DefaultEndpointsProtocol=https;AccountName=foo;AccountKey=bar;EndpointSuffix=core.windows.net"
        )
    )
    assert cfg.azure_storage_connection_string is not None
    assert cfg.azure_storage_account_name is None


def test_only_account_name_ok():
    cfg = BaseAgentSettings(**_dev_base(AZURE_STORAGE_ACCOUNT_NAME="storageacct"))
    assert cfg.azure_storage_account_name == "storageacct"
    assert cfg.azure_storage_connection_string is None
