"""``python -m agent_sdk`` — operator and developer commands.

rotate-master-key:
    Offline decrypt-all / re-encrypt-all under a new MASTER_KEY.
    Keys are read from env (MASTER_KEY / NEW_MASTER_KEY) or prompted
    without echo — never taken from argv (argv lands in shell history).

test-chat:
    Drive a live agentic turn against a booted agent over AG-UI (default)
    or A2A.  Boots the agent in-process via ``--app module:attr`` or talks
    to a running server via ``--url``.  Single-shot when a QUERY argument
    is given; interactive REPL when omitted.  Tool calls, A2UI surface
    sequences, and the final text reply are printed to stdout.

    A2A mode (``--a2a``) is HTTP+JSON-only (DESIGN.md non-goals §1): the
    target agent's card must advertise ``preferredTransport: "HTTP+JSON"``,
    or the driver raises ``ValueError``.  There is no gRPC or JSON-RPC
    transport support.

bump-patch:
    Increment the patch segment of the SDK version in ``pyproject.toml``
    (e.g. 0.4.0 → 0.4.1).  Run before every push to main so the released
    version is always monotonically increasing.

provision-org-oauth-client:
    Guided setup for ``AGENT_SDK_OAUTH_ONE_TIME_CONSENT`` (GH-136/GH-138).
    The setting has exactly two usable scopes, and this command exists
    because they are easy to conflate:

    * per-user (default — no setup needed): each connecting client's OWN
      DCR registration is remembered after an admin approves it once.
      A brand-new user still hits the admin gate the first time, because
      DCR mints a fresh, unconsented ``client_id`` per registration.
    * per-org (this command): registers and pre-approves ONE ``client_id``
      that every org member shares, by pinning it into the connector
      platform's static/pre-registered OAuth Client ID field instead of
      letting each user's client perform its own DCR call.

    Requires the exact ``redirect_uri`` the connector platform will use
    (get this from the platform's own connector setup screen BEFORE
    running this command — e.g. Claude.ai: Organization settings →
    Connectors → *connector* → Advanced settings) and prompts for explicit
    confirmation before minting a client every org member will share.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
import uuid
from pathlib import Path
from typing import Any


# ── rotate-master-key ─────────────────────────────────────────────────────────

def _key(env: str, prompt: str) -> str:
    value = os.environ.get(env)
    if value:
        return value
    return getpass.getpass(prompt)


def _cmd_rotate(args: argparse.Namespace) -> int:
    from .credentials.rotate import RotationError, rotate_master_key

    db = Path(args.db or os.environ.get("DATA_DIR", "./data"))
    if db.is_dir():
        db = db / "credentials.db"
    old_key = _key("MASTER_KEY", "Current MASTER_KEY: ")
    new_key = _key("NEW_MASTER_KEY", "New MASTER_KEY (>=32 chars): ")
    try:
        count = rotate_master_key(db, old_key, new_key)
    except RotationError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    print(f"rotated {count} credential(s) in {db}")
    print("Update MASTER_KEY in the deployment environment before restarting.")
    return 0


# ── test-chat ─────────────────────────────────────────────────────────────────

def _load_app(spec: str) -> Any:
    """Import ``module:attr`` like uvicorn does.  Inserts cwd into sys.path."""
    import importlib

    module_path, _, attr = spec.rpartition(":")
    if not module_path or not attr:
        raise SystemExit(f"--app must be 'module:attr', got {spec!r}")
    if "" not in sys.path:
        sys.path.insert(0, "")
    try:
        mod = importlib.import_module(module_path)
    except ModuleNotFoundError as exc:
        raise SystemExit(f"cannot import {module_path!r}: {exc}") from exc
    try:
        return getattr(mod, attr)
    except AttributeError as exc:
        raise SystemExit(f"{module_path!r} has no attribute {attr!r}") from exc


def _print_a2ui(messages: list, label: str) -> None:
    verbs = [next((k for k in m if k != "version"), "?") for m in messages]
    cs: dict[str, Any] = next((m.get("createSurface", {}) for m in messages if "createSurface" in m), {})
    uc: dict[str, Any] = next((m.get("updateComponents", {}) for m in messages if "updateComponents" in m), {})
    comp = (uc.get("components") or [{}])[0]
    print(
        f"  [A2UI:{label}]"
        f" component={comp.get('component')!r}"
        f"  catalog={cs.get('catalogId')}"
        f"  lifecycle={verbs}"
    )


async def _run_chat(args: argparse.Namespace) -> int:
    import httpx

    from .testing.chat import ChatDriver

    transport = "a2a" if args.a2a else "agui"
    query_text = " ".join(args.query).strip() if args.query else None
    catalogs: list[str] = list(args.catalog or [])

    # ── boot or connect ──
    if args.app:
        app = _load_app(args.app)
        ctx = app.router.lifespan_context(app)
        async with ctx:
            _, token = app.state.auth.api_keys.mint("test-chat", admin=True)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
                headers={"Authorization": f"Bearer {token}"},
                timeout=args.timeout,
            ) as client:
                return await _chat_loop(client, transport, query_text, catalogs, args.timeout)
    else:
        if not args.url:
            print("error: --app or --url is required", file=sys.stderr)
            return 2
        token = args.token or os.environ.get("AGENT_TOKEN") or ""
        if not token:
            print("error: --token or $AGENT_TOKEN is required with --url", file=sys.stderr)
            return 2
        async with httpx.AsyncClient(
            base_url=args.url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=args.timeout,
        ) as client:
            return await _chat_loop(client, transport, query_text, catalogs, args.timeout)


async def _chat_loop(
    client: object,
    transport: str,
    query_text: str | None,
    catalogs: list[str],
    timeout: float,
) -> int:
    driver = __import__("agent_sdk.testing.chat", fromlist=["ChatDriver"]).ChatDriver(
        client, extra_catalogs=catalogs, timeout=timeout
    )
    thread_id = uuid.uuid4().hex
    agui_messages: list = []
    a2a_context_id: str | None = None

    def _emit_agui() -> dict:
        tool_name_box: list = [None]

        def tool_start(name: str) -> None:
            tool_name_box[0] = name
            print(f"\n  [tool] {name}", end="", flush=True)

        def tool_args(args: dict) -> None:
            brief = ", ".join(f"{k}={v!r}" for k, v in args.items())
            if brief:
                print(f"({brief})", end="", flush=True)

        def tool_done() -> None:
            if tool_name_box[0]:
                print(" ✓", end="", flush=True)
                tool_name_box[0] = None

        def artifact(data_type: str, tool: str) -> None:
            print(f"\n  [artifact] {data_type}", end="", flush=True)

        def a2ui(messages: list) -> None:
            _print_a2ui(messages, "surface")

        def text(delta: str) -> None:
            # New line after any inline tool/surface output before first text.
            if delta:
                print(delta, end="", flush=True)

        def error(message: str) -> None:
            print(f"\n  [error] {message!r}", end="", flush=True)

        return {
            "tool_start": tool_start,
            "tool_args": tool_args,
            "tool_done": tool_done,
            "artifact": artifact,
            "a2ui": a2ui,
            "text": text,
            "error": error,
        }

    def _emit_a2a() -> dict:
        dot_count: list = [0]

        def tick() -> None:
            if dot_count[0] % 4 == 0:
                print(".", end="", flush=True)
            dot_count[0] += 1

        return {"tool_done": tick}

    async def turn(query: str) -> None:
        nonlocal a2a_context_id
        print(f"\nYOU  › {query}")
        print("AGENT › ", end="", flush=True)

        if transport == "agui":
            reply = await driver.agui_turn(query, thread_id, agui_messages, emit=_emit_agui())
            if not reply:
                print()
        else:
            task = await driver.a2a_turn(query, a2a_context_id, emit=_emit_a2a())
            print()
            a2a_context_id = task.get("contextId") or a2a_context_id
            for seq in driver.extract_a2ui(task):
                _print_a2ui(seq, "surface")
            reply = driver.extract_reply(task)
            if reply:
                print(reply)

    if query_text:
        await turn(query_text)
        print()
    else:
        print(f"agent test-chat  [{transport.upper()}]  —  Ctrl-C or 'exit' to quit")
        while True:
            try:
                q = input("\nYOU  › ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not q:
                continue
            if q.lower() in ("exit", "quit", "q"):
                break
            await turn(q)
    return 0


def _cmd_test_chat(args: argparse.Namespace) -> int:
    import asyncio

    return asyncio.run(_run_chat(args))


# ── migrate-store ─────────────────────────────────────────────────────────────

def _cmd_migrate_store(args: argparse.Namespace) -> int:
    """Migrate SQLite stores to Azure Table Storage.

    Reads AZURE_STORAGE_CONNECTION_STRING or AZURE_STORAGE_ACCOUNT_NAME from
    env.  Migrates credentials, pending commitments, and subscriptions from
    their respective SQLite files to Azure Table Storage.  The connection
    string is NEVER printed to stdout or stderr (SI-6).
    """
    import sqlite3

    data_dir = Path(args.data_dir)
    dry_run: bool = args.dry_run
    force: bool = args.force

    # 1. Resolve Azure settings from environment
    conn_str_raw = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    account_name = os.environ.get("AZURE_STORAGE_ACCOUNT_NAME")
    table_prefix = os.environ.get("AZURE_STORAGE_TABLE_PREFIX", "agent")

    if not conn_str_raw and not account_name:
        print(
            "error: neither AZURE_STORAGE_CONNECTION_STRING nor "
            "AZURE_STORAGE_ACCOUNT_NAME is set",
            file=sys.stderr,
        )
        return 1

    # ── credentials ──────────────────────────────────────────────────────────

    cred_count = 0
    cred_db = data_dir / "credentials.db"
    if cred_db.exists():
        master_key = os.environ.get("MASTER_KEY", "")
        if not master_key:
            print(
                "error: MASTER_KEY is required to decrypt credentials.db",
                file=sys.stderr,
            )
            return 1

        from .credentials.encrypted_sqlite import EncryptedSqliteStore
        from .credentials.azure_table import AzureTableCredentialStore
        from .models.errors import AgentError

        try:
            src_store = EncryptedSqliteStore(cred_db, master_key)
        except AgentError as err:
            print(f"error: {err.message}", file=sys.stderr)
            return 1

        if not dry_run:
            if conn_str_raw is not None:
                dst_cred = AzureTableCredentialStore(
                    master_key,
                    connection_string=conn_str_raw,
                    prefix=table_prefix,
                )
            else:
                dst_cred = AzureTableCredentialStore(
                    master_key,
                    account_name=account_name,
                    prefix=table_prefix,
                )

        # Collect all distinct namespaces from the sqlite3 file directly
        raw_conn = sqlite3.connect(str(cred_db))
        try:
            raw_conn.row_factory = sqlite3.Row
            namespaces = [
                row[0]
                for row in raw_conn.execute(
                    "SELECT DISTINCT namespace FROM credentials"
                ).fetchall()
            ]
        finally:
            raw_conn.close()

        for ns in namespaces:
            fields = src_store.list_fields(ns)
            for field in fields:
                plaintext = src_store.get(ns, field)
                if plaintext is None:
                    continue
                if dry_run:
                    cred_count += 1
                else:
                    if not force:
                        existing = dst_cred.get(ns, field)
                        if existing is not None:
                            continue
                    dst_cred.set(ns, field, plaintext)
                    cred_count += 1
        src_store.close()

    # ── commitments ──────────────────────────────────────────────────────────

    commit_count = 0
    commit_db = data_dir / "commitments.db"
    if commit_db.exists():
        from .contrib.commitments.store import CommitmentStore, STATUS_PENDING
        from .contrib.commitments.azure_table import AzureTableCommitmentStore

        src_commit = CommitmentStore(commit_db)
        src_commit.initialize()

        if not dry_run:
            if conn_str_raw is not None:
                dst_commit = AzureTableCommitmentStore(
                    connection_string=conn_str_raw,
                    table_prefix=table_prefix,
                )
            else:
                dst_commit = AzureTableCommitmentStore(
                    account_name=account_name,
                    table_prefix=table_prefix,
                )
            dst_commit.initialize()

        pending = src_commit.list(status=STATUS_PENDING, limit=10_000)
        for c in pending:
            if dry_run:
                commit_count += 1
            else:
                if not force:
                    existing_commit = dst_commit.get(c.id)
                    if existing_commit is not None:
                        continue
                import json as _json
                # Insert directly: bypass add() to preserve the original id
                # and fire_at. We use the Azure store's table client directly.
                from azure.data.tables import UpdateMode as _UpdateMode
                entity = {
                    "PartitionKey": AzureTableCommitmentStore.PARTITION_KEY,
                    "RowKey": c.id,
                    "tool": c.tool,
                    "args_json": _json.dumps(c.args),
                    "fire_at": c.fire_at,
                    "status": c.status,
                    "created_at": c.created_at,
                    "identity_binding": c.identity_binding,
                    "auth_context_json": _json.dumps(c.auth_context or {}),
                    "claimed_at": None,
                    "attempts": c.attempts,
                    "last_error": None,
                }
                dst_commit._table.upsert_entity(entity=entity, mode=_UpdateMode.REPLACE)
                commit_count += 1
        src_commit.close()

    # ── subscriptions ─────────────────────────────────────────────────────────

    sub_count = 0
    sub_db = data_dir / "webhook_subscriptions.db"
    if sub_db.exists():
        from .contrib.webhooks.subscriptions import SubscriptionStore
        from .contrib.webhooks.azure_table import AzureTableSubscriptionStore

        src_sub = SubscriptionStore(sub_db)
        src_sub.initialize()

        if not dry_run:
            if conn_str_raw is not None:
                dst_sub = AzureTableSubscriptionStore(
                    connection_string=conn_str_raw,
                    table_prefix=table_prefix,
                )
            else:
                dst_sub = AzureTableSubscriptionStore(
                    account_name=account_name,
                    table_prefix=table_prefix,
                )
            dst_sub.initialize()

        all_subs = src_sub.list()
        for sub in all_subs:
            if dry_run:
                sub_count += 1
            else:
                if not force:
                    existing_sub = dst_sub.get(sub["id"])
                    if existing_sub is not None:
                        continue
                dst_sub.upsert(
                    id=sub["id"],
                    resource=sub["resource"],
                    change_type=sub["change_type"],
                    notification_url=sub["notification_url"],
                    expiration=sub["expiration"],
                    lifecycle_url=sub.get("lifecycle_url"),
                    client_state_ref=sub.get("client_state_ref", "default"),
                    extra=sub.get("extra"),
                )
                sub_count += 1
        src_sub.close()

    # ── report ────────────────────────────────────────────────────────────────

    prefix = "[dry-run] would migrate" if dry_run else "migrated"
    print(f"credentials {prefix}: {cred_count}")
    print(f"pending commitments {prefix}: {commit_count}")
    print(f"subscriptions {prefix}: {sub_count}")
    return 0


# ── provision-org-oauth-client ──────────────────────────────────────────────

def _cmd_provision_org_oauth_client(args: argparse.Namespace) -> int:
    """Register + pre-approve ONE OAuth client for org-wide sharing.

    Runs the identical DCR registration (``OAuthTokenStore.register_client``)
    and admin-approval (``mark_consented``) steps the live ``/oauth/register``
    + ``/oauth/authorize`` routes perform over HTTP, but offline: this CLI's
    access to MASTER_KEY / the credential-store backend IS the admin trust
    boundary here, matching ``rotate-master-key``'s offline-operator model —
    there is no separate admin-API-key prompt.

    The minted ``client_id`` is not a secret (it identifies a registration,
    it does not authenticate one — PKCE does that), so it is printed in full
    for the operator to paste into the connector platform's static/
    pre-registered OAuth Client ID field.
    """
    from .auth.oauth_tokens import OAuthTokenStore
    from .routes.oauth import _valid_redirect_uri

    public_url = args.public_url or os.environ.get("PUBLIC_URL")
    if not public_url:
        print(
            "error: --public-url is required (or set $PUBLIC_URL) — org-wide "
            "provisioning needs the agent's real, reachable base URL",
            file=sys.stderr,
        )
        return 1
    base_url = public_url.rstrip("/")

    redirect_uri = args.redirect_uri
    if not redirect_uri:
        redirect_uri = input(
            "Redirect URI the connector platform will use "
            "(from its own connector setup screen): "
        ).strip()
    if not _valid_redirect_uri(redirect_uri):
        print(
            "error: redirect_uri must be https (or http://localhost / "
            "http://127.0.0.1) without a fragment",
            file=sys.stderr,
        )
        return 1

    if not args.yes:
        print(
            "\nThis mints ONE OAuth client that every user in your "
            "organization will share once pinned into the connector "
            "platform's static/pre-registered OAuth Client ID field.\n"
            "If you instead want each user's own connection to be "
            "remembered after an admin approves it once (per-user, the "
            "default), stop here — no setup is needed for that.\n"
        )
        confirmed = input("Type 'org' to confirm org-wide provisioning: ").strip()
        if confirmed != "org":
            print("Aborted — no client was registered.")
            return 1

    master_key = _key("MASTER_KEY", "MASTER_KEY: ")
    conn_str_raw = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    account_name = os.environ.get("AZURE_STORAGE_ACCOUNT_NAME")
    table_prefix = os.environ.get("AZURE_STORAGE_TABLE_PREFIX", "agent")
    if conn_str_raw:
        from .credentials.azure_table import AzureTableCredentialStore

        credential_store = AzureTableCredentialStore(
            master_key, connection_string=conn_str_raw, prefix=table_prefix
        )
    elif account_name:
        from .credentials.azure_table import AzureTableCredentialStore

        credential_store = AzureTableCredentialStore(
            master_key, account_name=account_name, prefix=table_prefix
        )
    else:
        from .credentials.encrypted_sqlite import EncryptedSqliteStore

        data_dir = Path(args.data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        credential_store = EncryptedSqliteStore(data_dir / "credentials.db", master_key)

    oauth_store = OAuthTokenStore(
        credential_store, issuer=base_url, canonical_resource=f"{base_url}/mcp"
    )
    record = oauth_store.register_client([redirect_uri], client_name=args.client_name)
    oauth_store.mark_consented(record["client_id"])

    print(f"\nRegistered + pre-approved client_id: {record['client_id']}")
    print(
        "\nPaste this Client ID into the connector platform's static/"
        "pre-registered OAuth Client ID field (Claude.ai: Organization "
        "settings → Connectors → <connector> → Advanced settings). Every "
        "org member who connects through that connector shares this ONE "
        "pre-approved registration."
    )
    print(
        "Ensure AGENT_SDK_OAUTH_ONE_TIME_CONSENT=true is set in this "
        "deployment's environment — without it, this registration still "
        "hits the admin gate on every authorize call."
    )
    return 0


# ── bump-patch ────────────────────────────────────────────────────────────────

def _cmd_bump_patch(args: argparse.Namespace) -> int:
    """Increment the patch segment in pyproject.toml (X.Y.Z → X.Y.Z+1)."""
    import re

    root = Path(__file__).parent.parent
    pyproject = root / "pyproject.toml"
    if not pyproject.exists():
        print(f"error: {pyproject} not found", file=sys.stderr)
        return 1

    text = pyproject.read_text()
    pattern = r'^(version\s*=\s*")(\d+)\.(\d+)\.(\d+)(")'
    match = re.search(pattern, text, re.MULTILINE)
    if not match:
        print('error: could not find version = "X.Y.Z" in pyproject.toml', file=sys.stderr)
        return 1

    major, minor, patch_ = int(match.group(2)), int(match.group(3)), int(match.group(4))
    old_ver = f"{major}.{minor}.{patch_}"
    new_ver = f"{major}.{minor}.{patch_ + 1}"
    new_text = re.sub(
        pattern,
        lambda m: f"{m.group(1)}{new_ver}{m.group(5)}",
        text,
        flags=re.MULTILINE,
    )
    pyproject.write_text(new_text)
    print(f"bumped {old_ver} → {new_ver}")
    return 0


# ── main ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m agent_sdk")
    sub = parser.add_subparsers(dest="command", required=True)

    # rotate-master-key
    rotate = sub.add_parser(
        "rotate-master-key",
        help="re-encrypt the credential store under a new MASTER_KEY (offline only)",
    )
    rotate.add_argument(
        "--db",
        help="credential store path or its directory (default: $DATA_DIR or ./data)",
    )
    rotate.set_defaults(fn=_cmd_rotate)

    # test-chat
    chat = sub.add_parser(
        "test-chat",
        help="drive a live agentic turn; prints query + reply as plain text",
    )
    src = chat.add_mutually_exclusive_group()
    src.add_argument(
        "--app",
        metavar="MODULE:ATTR",
        help="boot agent in-process from this ASGI app (e.g. src.main:app)",
    )
    src.add_argument(
        "--url",
        metavar="URL",
        help=(
            "base URL of a running agent (e.g. http://localhost:8045); "
            "with --a2a, only agents advertising preferredTransport=HTTP+JSON "
            "are supported (no gRPC/JSON-RPC — see DESIGN.md non-goals)"
        ),
    )
    chat.add_argument(
        "--token",
        metavar="TOKEN",
        help="bearer token for --url (or set $AGENT_TOKEN)",
    )
    chat.add_argument(
        "--a2a",
        action="store_true",
        help="use A2A transport instead of AG-UI (default: AG-UI)",
    )
    chat.add_argument(
        "--catalog",
        metavar="CATALOG_ID",
        action="append",
        help="declare extra A2UI domain catalog in capability claim (repeatable)",
    )
    chat.add_argument(
        "--timeout",
        type=float,
        default=180.0,
        metavar="SECONDS",
        help="per-turn timeout in seconds (default: 180)",
    )
    chat.add_argument(
        "query",
        nargs="*",
        help="query text; omit for interactive REPL",
    )
    chat.set_defaults(fn=_cmd_test_chat)

    # migrate-store
    migrate = sub.add_parser(
        "migrate-store",
        help=(
            "migrate SQLite credential/commitment/subscription stores to "
            "Azure Table Storage (reads AZURE_STORAGE_CONNECTION_STRING or "
            "AZURE_STORAGE_ACCOUNT_NAME from env)"
        ),
    )
    migrate.add_argument(
        "--data-dir",
        default="./data",
        metavar="DIR",
        help="directory containing SQLite store files (default: ./data)",
    )
    migrate.add_argument(
        "--dry-run",
        action="store_true",
        help="print what would be migrated without writing to Azure",
    )
    migrate.add_argument(
        "--force",
        action="store_true",
        help="overwrite existing Azure entities (default: skip collisions)",
    )
    migrate.set_defaults(fn=_cmd_migrate_store)

    # provision-org-oauth-client
    provision = sub.add_parser(
        "provision-org-oauth-client",
        help=(
            "register + pre-approve ONE OAuth client for org-wide sharing "
            "(guided setup for AGENT_SDK_OAUTH_ONE_TIME_CONSENT's per-org scope)"
        ),
    )
    provision.add_argument(
        "--redirect-uri",
        metavar="URI",
        help="the exact redirect_uri the connector platform will use (prompted if omitted)",
    )
    provision.add_argument(
        "--client-name",
        metavar="NAME",
        help="human-readable label for this registration (optional)",
    )
    provision.add_argument(
        "--public-url",
        metavar="URL",
        help="agent's public base URL (default: $PUBLIC_URL)",
    )
    provision.add_argument(
        "--data-dir",
        default="./data",
        metavar="DIR",
        help="directory for the SQLite credential store when Azure env vars are unset (default: ./data)",
    )
    provision.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="skip the interactive org-wide confirmation prompt",
    )
    provision.set_defaults(fn=_cmd_provision_org_oauth_client)

    # bump-patch
    bump = sub.add_parser(
        "bump-patch",
        help="increment the patch version in pyproject.toml (X.Y.Z → X.Y.Z+1)",
    )
    bump.set_defaults(fn=_cmd_bump_patch)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
