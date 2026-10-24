"""Internal error model.

``AgentError`` is the SDK-internal error envelope (DESIGN.md §5.1). It is
never serialized to a wire as-is; each protocol route maps it to its own
wire error shape (A2A JSON-RPC-style error object, MCP isError result,
AG-UI RUN_ERROR). Error messages must never contain input values or
credentials.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class ErrorCategory(StrEnum):
    AUTH = "auth"
    NOT_FOUND = "not_found"
    RATE_LIMITED = "rate_limited"
    UPSTREAM = "upstream"
    VALIDATION = "validation"
    TIMEOUT = "timeout"
    BUDGET = "budget"
    INTERNAL = "internal"


# A2A v0.3.0 error codes — complete table per DESIGN.md §5.1.
A2A_TASK_NOT_FOUND = -32001
A2A_TASK_NOT_CANCELABLE = -32002
A2A_PUSH_NOTIFICATION_NOT_SUPPORTED = -32003
A2A_UNSUPPORTED_OPERATION = -32004
A2A_CONTENT_TYPE_NOT_SUPPORTED = -32005
A2A_INVALID_AGENT_RESPONSE = -32006
A2A_AUTHENTICATED_EXTENDED_CARD_NOT_CONFIGURED = -32007

A2A_ERROR_NAMES: dict[int, str] = {
    A2A_TASK_NOT_FOUND: "TaskNotFound",
    A2A_TASK_NOT_CANCELABLE: "TaskNotCancelable",
    A2A_PUSH_NOTIFICATION_NOT_SUPPORTED: "PushNotificationNotSupported",
    A2A_UNSUPPORTED_OPERATION: "UnsupportedOperation",
    A2A_CONTENT_TYPE_NOT_SUPPORTED: "ContentTypeNotSupported",
    A2A_INVALID_AGENT_RESPONSE: "InvalidAgentResponse",
    A2A_AUTHENTICATED_EXTENDED_CARD_NOT_CONFIGURED: "AuthenticatedExtendedCardNotConfigured",
}

# HTTP status for each A2A error on the HTTP+JSON transport.
# -32000 (JSON-RPC implementation-defined server error) and -32601 (JSON-RPC
# Method not found) are reverse-only: app.py's generic HTTP exception handler
# maps bare 401/403 -> -32000 and 404 -> -32601 for dispatch-level failures
# that never construct a WireError here, so neither has a forward entry.
# WireError.from_a2a_code(-32000 | -32601, ...).http_status() intentionally
# falls back to the 500 default; do not add entries for them without also
# reconciling the app.py dispatch-level status codes (401/403 and 404).
A2A_HTTP_STATUS: dict[int, int] = {
    A2A_TASK_NOT_FOUND: 404,
    A2A_TASK_NOT_CANCELABLE: 409,
    A2A_PUSH_NOTIFICATION_NOT_SUPPORTED: 501,  # capability absent, not a bad request
    A2A_UNSUPPORTED_OPERATION: 501,
    A2A_CONTENT_TYPE_NOT_SUPPORTED: 415,  # Unsupported Media Type
    A2A_INVALID_AGENT_RESPONSE: 502,  # upstream/model produced an invalid response
    A2A_AUTHENTICATED_EXTENDED_CARD_NOT_CONFIGURED: 501,  # feature not implemented
}


class SafeValueError(ValueError):
    """A validator rejection whose fixed hint may reach the caller (GH-230).

    Subclass it, set the class attribute ``message`` to fixed guidance text and
    raise it with no arguments. Only ``type(err).message`` is ever rendered;
    anything passed at raise time is dropped, so never put input in the class
    text.
    """

    message: str = ""


class AgentError(Exception):
    """Raised by tools/adapters; translated per surface, never crashes the loop."""

    def __init__(
        self,
        category: ErrorCategory,
        message: str,
        *,
        source: str | None = None,
        a2a_code: int | None = None,
        detail: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.message = message
        self.source = source
        self.a2a_code = a2a_code
        self.detail = detail or {}

    def public(self) -> dict:
        """Shape safe to show a consumer (no input values, no credentials)."""
        out: dict = {"category": self.category.value, "message": self.message}
        if self.source:
            out["source"] = self.source
        return out


class WireError(BaseModel):
    """A2A wire error object: the spec `{code, message, data?}` shape."""

    code: int
    message: str
    data: dict | None = None

    @classmethod
    def from_a2a_code(cls, code: int, message: str | None = None) -> "WireError":
        return cls(code=code, message=message or A2A_ERROR_NAMES.get(code, "Error"))

    def http_status(self) -> int:
        return A2A_HTTP_STATUS.get(self.code, 500)
