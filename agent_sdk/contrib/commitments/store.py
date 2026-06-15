"""Durable commitment store — SQLite-backed scheduled tool execution (DESIGN §9).

A *commitment* is a registered tool plus its arguments plus a future ``fire_at``
UTC instant. The store persists it across restarts; the background
:class:`~agent_sdk.contrib.commitments.executor.CommitmentExecutor` polls for due
rows and fires them. Generalized from the m365 reference, with two deliberate
hardenings the reference lacked:

1. **At-most-once claim.** Firing is a two-state transition: a due ``pending`` row
   is atomically flipped to ``firing`` by a guarded ``UPDATE ... WHERE status =
   'pending'`` — only the writer whose ``rowcount == 1`` owns it. Two pollers
   (two processes, or an overlapping tick) can never both fire the same
   side-effecting tool. The terminal transition is guarded the same way
   (``mark_fired``/``mark_failed`` only complete a row still in ``firing``), so a
   late completion can never relabel a row the reaper already moved — it returns
   ``False`` and the caller must not retry. A row left in ``firing`` by a crash
   (or a tool that outran its lease) is reaped to ``failed`` (never auto-retried
   — a re-run could double-send). NOTE: pick ``lease_seconds`` larger than the
   slowest tool's runtime, or a still-running fire can be reaped mid-flight and
   recorded ``failed`` even though it ultimately succeeded.
2. **Canonical ``fire_at``.** Every ``fire_at`` is normalized to fixed-width UTC
   ``...Z`` on insert, so the cheap lexicographic ``fire_at <= now`` SQL
   comparison is also chronologically correct (raw ISO strings with mixed
   offsets would mis-sort).

House SQLite style (matches ``EncryptedSqliteStore``): one persistent stdlib
``sqlite3`` connection guarded by a ``threading.Lock``, parameterized ``?`` binds
only, explicit ``commit()``, ``CREATE TABLE IF NOT EXISTS`` inline.

**Secrets hygiene (DESIGN §6 / standing instruction):** never schedule a live
secret. ``add`` REFUSES args containing a secret-named key (forwarding the rule
to the boundary, not just documenting it) and masks any secret-named value in
``auth_context`` before persisting. The persisted ``auth_context`` is meant to
hold a *re-mintable reference* (e.g. an OBO ``home_account_id``), not a token —
the executor's ``fire_auth`` hook re-establishes live credentials at fire time.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ...common.redact import _SECRET_KEY, redact, redact_value
# Commitment is defined in backend.py (to avoid circular imports) and
# re-exported here so store consumers have a single import point.
from .backend import Commitment, CommitmentBackend

# Lifecycle states. pending → firing → (fired | failed); pending → cancelled.
STATUS_PENDING = "pending"
STATUS_FIRING = "firing"
STATUS_FIRED = "fired"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

# Cap persisted JSON so a single commitment cannot bloat the DB / slow scans.
_MAX_JSON_BYTES = 64 * 1024
# Cap a stored failure reason (defense-in-depth — see mark_failed).
_MAX_REASON_LEN = 200

_DDL = """
CREATE TABLE IF NOT EXISTS commitments(
    id                TEXT PRIMARY KEY,
    tool              TEXT NOT NULL,
    args_json         TEXT NOT NULL,
    fire_at           TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'pending',
    created_at        TEXT NOT NULL,
    identity_binding  TEXT,
    auth_context_json TEXT NOT NULL DEFAULT '{}',
    claimed_at        TEXT,
    attempts          INTEGER NOT NULL DEFAULT 0,
    last_error        TEXT
)
"""

_DDL_IDX = (
    "CREATE INDEX IF NOT EXISTS idx_commitments_status_fire_at "
    "ON commitments(status, fire_at)"
)


def _utcnow_iso() -> str:
    """Canonical fixed-width UTC instant (lexicographically comparable)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_fire_at(fire_at: str) -> str:
    """Parse an ISO 8601 ``fire_at`` and re-emit it in canonical UTC ``...Z``
    form. A naive (offset-less) value is interpreted as UTC. Raises
    ``ValueError`` on anything unparseable — the input boundary rejects junk so
    nothing malformed reaches the comparison or the DB."""
    if not isinstance(fire_at, str):
        raise ValueError("fire_at must be an ISO 8601 string")
    parsed = datetime.fromisoformat(fire_at.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _has_secret_key(obj: Any, _depth: int = 0) -> bool:
    """True if any dict key (recursively) matches the secret-name pattern — used
    to REFUSE scheduling a live secret inside tool args. Fails CLOSED: anything
    nested too deep to fully inspect is treated as if it held a secret (mirrors
    ``redact``, which collapses an over-deep subtree to ``[redacted]`` — the
    refusal must not be laxer than the masking, or a deeply-buried secret could
    slip past the check and land verbatim in the DB)."""
    if _depth > 8:
        return True
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str) and _SECRET_KEY.search(k):
                return True
            if _has_secret_key(v, _depth + 1):
                return True
    elif isinstance(obj, (list, tuple)):
        return any(_has_secret_key(v, _depth + 1) for v in obj)
    return False


def _dump_json(obj: Any, label: str) -> str:
    """Serialize ``obj`` to JSON for persistence, mapping non-serializable input
    and oversize payloads to a generic ``ValueError``. The boundary rejects junk
    so the poller never trips on an undecodable row, and the message never echoes
    a value (secrets hygiene)."""
    try:
        text = json.dumps(obj)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be JSON-serializable") from exc
    if len(text.encode("utf-8")) > _MAX_JSON_BYTES:
        raise ValueError(f"{label} exceeds the {_MAX_JSON_BYTES}-byte limit")
    return text


class CommitmentStore(CommitmentBackend):
    """SQLite-backed durable store for scheduled tool commitments (DESIGN §9)."""

    def __init__(self, db_path: str | Path = "commitments.db") -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # Wait (don't fail) if another process holds the write lock mid-claim.
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._closed = False

    def initialize(self) -> None:
        """Create the table + index if absent. Idempotent."""
        self._ensure_open()
        with self._lock:
            self._conn.execute(_DDL)
            self._conn.execute(_DDL_IDX)
            self._conn.commit()

    # ── write ──
    def add(
        self,
        *,
        tool: str,
        args: dict[str, Any],
        fire_at: str,
        identity_binding: str | None = None,
        auth_context: dict[str, Any] | None = None,
    ) -> str:
        """Insert a pending commitment; return its generated id.

        ``fire_at`` is validated + normalized to canonical UTC (raises
        ``ValueError`` if unparseable). ``args`` is REFUSED if it contains a
        secret-named key (never schedule a live secret — see module docstring).
        ``auth_context`` secret-named values are masked before persisting; it is
        meant to carry a re-mintable reference, not a token."""
        if not tool or not isinstance(tool, str):
            raise ValueError("tool must be a non-empty registered tool name")
        if not isinstance(args, dict):
            raise ValueError("args must be a dict")
        if identity_binding is not None and not (
            isinstance(identity_binding, str) and identity_binding.strip()
        ):
            # An empty/blank binding is NOT a valid owner key — it would collapse
            # every "unknown identity" caller into one shared bucket (cross-user
            # read/cancel, and, when bridged to OBO, cross-user re-mint). Force
            # None (the explicit admin/unbound path) or a real owner key.
            raise ValueError("identity_binding must be a non-empty owner key or None")
        if _has_secret_key(args):
            # Generic message — never echo the offending key/value.
            raise ValueError(
                "args must not contain a secret-named key; persist a re-mintable "
                "reference in auth_context and re-establish credentials in fire_auth"
            )
        norm_fire_at = _normalize_fire_at(fire_at)
        args_json = _dump_json(args, "args")
        auth_json = _dump_json(redact(auth_context or {}), "auth_context")
        commitment_id = str(uuid.uuid4())
        created_at = _utcnow_iso()
        self._ensure_open()
        with self._lock:
            self._conn.execute(
                "INSERT INTO commitments"
                " (id, tool, args_json, fire_at, status, created_at,"
                "  identity_binding, auth_context_json, attempts)"
                " VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, 0)",
                (
                    commitment_id,
                    tool,
                    args_json,
                    norm_fire_at,
                    created_at,
                    identity_binding,
                    auth_json,
                ),
            )
            self._conn.commit()
        return commitment_id

    def claim_due(self, now: str | None = None, limit: int = 50) -> list[Commitment]:
        """Atomically claim up to ``limit`` due pending commitments, returning
        the claimed rows. Each row is flipped ``pending`` → ``firing`` by a
        guarded UPDATE; only rows this caller actually won (``rowcount == 1``)
        are returned — so two concurrent pollers never both fire the same row."""
        now = now or _utcnow_iso()
        claimed_at = _utcnow_iso()
        self._ensure_open()
        with self._lock:
            cur = self._conn.execute(
                "SELECT id FROM commitments"
                " WHERE status = 'pending' AND fire_at <= ?"
                " ORDER BY fire_at LIMIT ?",
                (now, limit),
            )
            candidate_ids = [row["id"] for row in cur.fetchall()]
            won: list[str] = []
            for cid in candidate_ids:
                upd = self._conn.execute(
                    "UPDATE commitments SET status = 'firing', claimed_at = ?,"
                    " attempts = attempts + 1 WHERE id = ? AND status = 'pending'",
                    (claimed_at, cid),
                )
                if upd.rowcount == 1:
                    won.append(cid)
            self._conn.commit()
            rows = [self._fetch_row(cid) for cid in won]
        return [self._to_commitment(r) for r in rows if r is not None]

    def mark_fired(self, commitment_id: str) -> bool:
        """Complete a claimed (``firing``) commitment as ``fired``. Returns True
        iff THIS call owned the transition; False means the row already left
        ``firing`` (e.g. reaped after a lease overrun) — the caller MUST NOT
        retry (the side effect already ran)."""
        return self._set_terminal(commitment_id, STATUS_FIRED, None)

    def mark_failed(self, commitment_id: str, reason: str | None) -> bool:
        """Mark a claimed commitment ``failed``. The caller should pass only a
        short, non-secret string (an error category or exception type name); as
        defense-in-depth for the HARD 'no secrets in the DB' rule this sink also
        bearer-scrubs and truncates ``reason`` rather than trusting the caller.
        Returns True iff THIS call owned the transition (see :meth:`mark_fired`)."""
        safe = redact_value(str(reason or ""))[:_MAX_REASON_LEN]
        return self._set_terminal(commitment_id, STATUS_FAILED, safe)

    def cancel(self, commitment_id: str, *, identity_binding: str | None = None) -> bool:
        """Cancel a still-pending commitment. Identity-bound: when
        ``identity_binding`` is given, only a row with the matching binding is
        cancelled (mismatch → no-op, returns False — existence is not leaked).
        ``identity_binding=None`` is the admin/unbound path. Returns True iff a
        row transitioned to cancelled."""
        self._ensure_open()
        with self._lock:
            if identity_binding is None:
                cur = self._conn.execute(
                    "UPDATE commitments SET status = 'cancelled'"
                    " WHERE id = ? AND status = 'pending'",
                    (commitment_id,),
                )
            else:
                cur = self._conn.execute(
                    "UPDATE commitments SET status = 'cancelled'"
                    " WHERE id = ? AND status = 'pending' AND identity_binding = ?",
                    (commitment_id, identity_binding),
                )
            self._conn.commit()
            return cur.rowcount == 1

    def reap_stale_firing(self, lease_seconds: int) -> int:
        """Move rows stuck in ``firing`` longer than ``lease_seconds`` to
        ``failed``. A row reaches ``firing`` only when claimed; if the process
        dies before ``mark_fired``/``mark_failed`` it stays there. It is failed,
        NOT retried — re-running a side-effecting tool could double-act, and we
        cannot know whether the side effect already happened. Returns the count
        reaped. Call once at startup (crash recovery) and each tick."""
        cutoff = (
            datetime.now(timezone.utc) - timedelta(seconds=max(0, lease_seconds))
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._ensure_open()
        with self._lock:
            cur = self._conn.execute(
                "UPDATE commitments SET status = 'failed',"
                " last_error = 'lease_expired'"
                " WHERE status = 'firing' AND claimed_at IS NOT NULL"
                " AND claimed_at < ?",
                (cutoff,),
            )
            self._conn.commit()
            return cur.rowcount

    # ── read ──
    def get(
        self, commitment_id: str, *, identity_binding: str | None = None
    ) -> Commitment | None:
        """Identity-bound lookup (mirrors the task store): a binding mismatch
        returns None rather than leaking existence. ``identity_binding=None``
        bypasses the check (admin/unbound)."""
        self._ensure_open()
        with self._lock:
            row = self._fetch_row(commitment_id)
        if row is None:
            return None
        if identity_binding is not None and row["identity_binding"] != identity_binding:
            return None
        return self._to_commitment(row)

    def list(
        self,
        *,
        identity_binding: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[Commitment]:
        """List commitments, newest first. Scoped to ``identity_binding`` when
        given; optionally filtered by ``status``."""
        clauses: list[str] = []
        params: list[Any] = []
        if identity_binding is not None:
            clauses.append("identity_binding = ?")
            params.append(identity_binding)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        self._ensure_open()
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM commitments" + where
                + " ORDER BY created_at DESC LIMIT ?",
                tuple(params),
            )
            rows = cur.fetchall()
        return [self._to_commitment(r) for r in rows]

    # ── lifecycle ──
    def close(self) -> None:
        """Close the connection. Idempotent (the executor lifespan and the
        owning source may both close it)."""
        with self._lock:
            if not self._closed:
                self._conn.close()
                self._closed = True

    def __del__(self) -> None:
        self.close()

    # ── internals ──
    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("commitment store is closed")

    def _set_terminal(self, commitment_id: str, status: str, reason: str | None) -> bool:
        """Complete a row the firer still owns. Guarded on ``status='firing'`` so
        a late ``mark_fired`` can never relabel a row the reaper already moved to
        ``failed`` (and vice versa) — the terminal transition is as at-most-once
        as the claim itself. Returns True iff exactly this call transitioned it."""
        self._ensure_open()
        with self._lock:
            cur = self._conn.execute(
                "UPDATE commitments SET status = ?, last_error = ?"
                " WHERE id = ? AND status = 'firing'",
                (status, reason, commitment_id),
            )
            self._conn.commit()
            return cur.rowcount == 1

    def _fetch_row(self, commitment_id: str) -> sqlite3.Row | None:
        cur = self._conn.execute(
            "SELECT * FROM commitments WHERE id = ?", (commitment_id,)
        )
        return cur.fetchone()

    @staticmethod
    def _to_commitment(row: sqlite3.Row) -> Commitment:
        return Commitment(
            id=row["id"],
            tool=row["tool"],
            args=json.loads(row["args_json"]),
            fire_at=row["fire_at"],
            status=row["status"],
            created_at=row["created_at"],
            identity_binding=row["identity_binding"],
            auth_context=json.loads(row["auth_context_json"] or "{}"),
            attempts=row["attempts"],
        )


__all__ = [
    "CommitmentStore",
    "Commitment",  # Re-exported from backend for store consumers; canonical definition in backend.py
    "STATUS_PENDING",
    "STATUS_FIRING",
    "STATUS_FIRED",
    "STATUS_FAILED",
    "STATUS_CANCELLED",
]
