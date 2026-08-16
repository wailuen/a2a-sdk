"""Tests for `python -m agent_sdk provision-org-oauth-client` (GH-138)."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch

_MASTER_KEY = "test-master-key-for-provision-32x"
_REDIRECT_URI = "https://claude.ai/api/mcp/auth_callback"
_PUBLIC_URL = "https://agent.example.com"


def _run(argv: list[str], env: dict[str, str] | None = None) -> tuple[int, str]:
    """Invoke ``agent_sdk.__main__.main()`` and capture stdout."""
    from agent_sdk.__main__ import main

    env = env if env is not None else {"MASTER_KEY": _MASTER_KEY}
    captured = io.StringIO()
    with patch.dict("os.environ", env, clear=False), patch("sys.stdout", captured):
        rc = main(argv)
    return rc, captured.getvalue()


def _clients(data_dir: Path) -> list[dict]:
    from agent_sdk.credentials.encrypted_sqlite import EncryptedSqliteStore
    from agent_sdk.credentials.store import NS_OAUTH_CLIENTS

    store = EncryptedSqliteStore(data_dir / "credentials.db", _MASTER_KEY)
    try:
        import json

        return [
            json.loads(store.get(NS_OAUTH_CLIENTS, field))
            for field in store.list_fields(NS_OAUTH_CLIENTS)
        ]
    finally:
        store.close()


def test_registers_and_preapproves_client(tmp_path):
    rc, out = _run(
        [
            "provision-org-oauth-client",
            "--redirect-uri",
            _REDIRECT_URI,
            "--public-url",
            _PUBLIC_URL,
            "--data-dir",
            str(tmp_path),
            "--yes",
        ]
    )
    assert rc == 0

    clients = _clients(tmp_path)
    assert len(clients) == 1
    assert clients[0]["consented"] is True
    assert clients[0]["redirect_uris"] == [_REDIRECT_URI]
    assert clients[0]["client_id"] in out
    assert "Organization settings" in out
    assert "AGENT_SDK_OAUTH_ONE_TIME_CONSENT" in out


def test_client_name_stored(tmp_path):
    rc, _ = _run(
        [
            "provision-org-oauth-client",
            "--redirect-uri",
            _REDIRECT_URI,
            "--public-url",
            _PUBLIC_URL,
            "--data-dir",
            str(tmp_path),
            "--client-name",
            "org-shared-connector",
            "--yes",
        ]
    )
    assert rc == 0
    clients = _clients(tmp_path)
    assert clients[0]["client_name"] == "org-shared-connector"


def test_missing_public_url_exits_1(tmp_path, capsys):
    rc, _ = _run(
        [
            "provision-org-oauth-client",
            "--redirect-uri",
            _REDIRECT_URI,
            "--data-dir",
            str(tmp_path),
            "--yes",
        ],
        env={"MASTER_KEY": _MASTER_KEY},
    )
    assert rc == 1
    assert _clients(tmp_path) == []


def test_invalid_redirect_uri_exits_1(tmp_path):
    rc, _ = _run(
        [
            "provision-org-oauth-client",
            "--redirect-uri",
            "javascript://evil",
            "--public-url",
            _PUBLIC_URL,
            "--data-dir",
            str(tmp_path),
            "--yes",
        ]
    )
    assert rc == 1
    assert _clients(tmp_path) == []


def test_confirmation_declined_registers_nothing(tmp_path):
    with patch("builtins.input", return_value="no"):
        rc, out = _run(
            [
                "provision-org-oauth-client",
                "--redirect-uri",
                _REDIRECT_URI,
                "--public-url",
                _PUBLIC_URL,
                "--data-dir",
                str(tmp_path),
            ]
        )
    assert rc == 1
    assert "Aborted" in out
    assert _clients(tmp_path) == []


def test_confirmation_accepted_via_prompt(tmp_path):
    with patch("builtins.input", return_value="org"):
        rc, _ = _run(
            [
                "provision-org-oauth-client",
                "--redirect-uri",
                _REDIRECT_URI,
                "--public-url",
                _PUBLIC_URL,
                "--data-dir",
                str(tmp_path),
            ]
        )
    assert rc == 0
    assert len(_clients(tmp_path)) == 1


def test_public_url_from_env(tmp_path):
    rc, _ = _run(
        [
            "provision-org-oauth-client",
            "--redirect-uri",
            _REDIRECT_URI,
            "--data-dir",
            str(tmp_path),
            "--yes",
        ],
        env={"MASTER_KEY": _MASTER_KEY, "PUBLIC_URL": _PUBLIC_URL},
    )
    assert rc == 0
    assert len(_clients(tmp_path)) == 1
