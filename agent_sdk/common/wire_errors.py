"""Wire error builders (DESIGN.md §5.1).

``AgentError`` is internal-only; these helpers emit the spec error shape
``{code, message, data?}`` with the documented HTTP status mapping. Never
echo input values or credentials.
"""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse

from ..models.errors import A2A_HTTP_STATUS, AgentError, ErrorCategory

_CATEGORY_HTTP = {
    ErrorCategory.AUTH: 401,
    ErrorCategory.NOT_FOUND: 404,
    ErrorCategory.RATE_LIMITED: 429,
    ErrorCategory.UPSTREAM: 502,
    ErrorCategory.VALIDATION: 400,
    ErrorCategory.TIMEOUT: 504,
    ErrorCategory.BUDGET: 429,
    ErrorCategory.INTERNAL: 500,
}

_PARSE_ERROR = -32700
_INVALID_PARAMS = -32602
_INVALID_REQUEST = -32600
_METHOD_NOT_FOUND = -32601
_INTERNAL_ERROR = -32603

_CLIENT_CODE_HTTP = {
    _PARSE_ERROR: 400,
    _INVALID_PARAMS: 400,
    _INVALID_REQUEST: 400,
    _METHOD_NOT_FOUND: 404,
}


def a2a_error(
    code: int,
    message: str,
    data: Any = None,
    *,
    headers: dict[str, str] | None = None,
    status: int | None = None,
) -> JSONResponse:
    """A2A spec error (the seven -3200x codes or JSON-RPC standard codes).

    ``headers`` (RT-B-005/RT-005): a caller on the ``/v1/*`` surface may pass
    an already-computed ``X-A2A-Extensions`` echo so it survives on an error
    response too — this JSONResponse is returned directly, bypassing
    FastAPI's normal merge of the injected ``Response`` object's headers.
    Pass it ONLY once the caller has established, for THIS response, what was
    genuinely activated — never a header pre-computed before the request's
    own branch (parse/config failure vs. a resolved success path) was known;
    routes/a2a.py's module docstring and ``_echo_extensions`` document why.
    ``status`` overrides the per-code HTTP status for one call site (GH-266:
    a wrong-state message answers -32004 with 400, not the 501 default).
    Most error paths (a parse failure, an unresolvable resume, ...) activated
    nothing and correctly pass no headers at all.
    """
    if status is None:
        status = A2A_HTTP_STATUS.get(code, _CLIENT_CODE_HTTP.get(code, 500))
    body: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        body["data"] = data
    return JSONResponse(status_code=status, content={"error": body}, headers=headers)


def a2a_parse_error(
    message: str = "parse error", *, headers: dict[str, str] | None = None
) -> JSONResponse:
    return a2a_error(_PARSE_ERROR, message, headers=headers)


def a2a_invalid_params(
    message: str = "invalid params", *, headers: dict[str, str] | None = None
) -> JSONResponse:
    return a2a_error(_INVALID_PARAMS, message, headers=headers)


def from_agent_error(err: AgentError) -> JSONResponse:
    """Generic HTTP mapping for non-A2A surfaces (admin, console APIs)."""
    public = err.public()  # dict: {category, message, source?}
    if err.a2a_code is not None:
        return a2a_error(err.a2a_code, public["message"])
    status = _CATEGORY_HTTP.get(err.category, 500)
    return JSONResponse(status_code=status, content={"error": public})
