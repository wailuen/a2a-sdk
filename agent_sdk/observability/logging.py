"""Structured logging with secret redaction.

stdlib-only (the SDK adds no logging dependency): one JSON line per record,
``redact()`` applied to every rendered message so a credential that reaches
a log call never reaches the log file.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any

from ..common.redact import redact_value
from .tracing import current_request_id


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": redact_value(record.getMessage()),
        }
        request_id = current_request_id()
        if request_id:
            entry["request_id"] = request_id
        if record.exc_info:
            entry["exc"] = redact_value(self.formatException(record.exc_info))
        return json.dumps(entry, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    """Idempotent root configuration; uvicorn's handlers are left alone."""
    root = logging.getLogger("agent_sdk")
    if any(getattr(h, "_agent_sdk", False) for h in root.handlers):
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_JsonFormatter())
    handler._agent_sdk = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel(level)
    root.propagate = False


class _OAuthQueryFilter(logging.Filter):
    """Drops the query string of /oauth/ paths from uvicorn access records."""

    _agent_sdk = True

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            path = args[2]
            if path.startswith("/oauth/") and "?" in path:
                record.args = (*args[:2], path.split("?", 1)[0], *args[3:])
        return True


def configure_access_log_filter() -> None:
    """Idempotent: strip /oauth/ query strings (code, state) from uvicorn.access."""
    access = logging.getLogger("uvicorn.access")
    if any(getattr(f, "_agent_sdk", False) for f in access.filters):
        return
    access.addFilter(_OAuthQueryFilter())
