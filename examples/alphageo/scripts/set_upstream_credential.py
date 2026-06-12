"""Seed the AlphaGeo upstream vendor key into the encrypted credential store.

Per ADR 0001 the upstream key lives at namespace ``alphageo`` / field
``api_key`` — the *stored fallback* the adapter resolves when no key is
forwarded on ``X-Agent-Credentials``. It is NEVER a setting and never goes in
``.env``.

Usage (load your ``.env`` into the environment first so MASTER_KEY/DATA_DIR are
set, e.g. ``set -a; . .env; set +a``)::

    # value from an env var (CI / scripted):
    ALPHAGEO_UPSTREAM_KEY=... python scripts/set_upstream_credential.py

    # or interactively (value is read without echo):
    python scripts/set_upstream_credential.py

This prints only a masked confirmation (field name + length). It never prints,
logs, or echoes the key value or MASTER_KEY.
"""

from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

from agent_sdk.credentials.encrypted_sqlite import EncryptedSqliteStore

NAMESPACE = "alphageo"
FIELD = "api_key"


def main() -> int:
    master_key = os.environ.get("MASTER_KEY")
    if not master_key:
        print(
            "MASTER_KEY is not set. Load your .env first "
            "(set -a; . .env; set +a), then re-run.",
            file=sys.stderr,
        )
        return 2
    data_dir = os.environ.get("DATA_DIR", "./data")

    value = os.environ.get("ALPHAGEO_UPSTREAM_KEY")
    if not value:
        value = getpass.getpass("AlphaGeo upstream API key (input hidden): ")
    value = value.strip()
    if not value:
        print("No key provided; nothing written.", file=sys.stderr)
        return 2

    db_path = Path(data_dir) / "credentials.db"
    store = EncryptedSqliteStore(db_path, master_key)
    try:
        store.set(NAMESPACE, FIELD, value)
        fields = store.list_fields(NAMESPACE)
    finally:
        store.close()

    # Masked confirmation only — length, never the value.
    print(
        f"OK: seeded {NAMESPACE}/{FIELD} (length={len(value)}) into {db_path}. "
        f"Fields now in '{NAMESPACE}' namespace: {fields}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
