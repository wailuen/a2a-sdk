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
_INTERNAL_ERROR = -32603


def a2a_error(code: int, message: str, data: Any = None) -> JSONResponse:
    """A2A spec error (the seven -3200x codes or JSON-RPC standard codes)."""
    _client_error_codes = (_PARSE_ERROR, _INVALID_PARAMS)
    status = A2A_HTTP_STATUS.get(code, 400 if code in _client_error_codes else 500)
    body: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        body["data"] = data
    return JSONResponse(status_code=status, content={"error": body})


def a2a_parse_error(message: str = "parse error") -> JSONResponse:
    return a2a_error(_PARSE_ERROR, message)


def a2a_invalid_params(message: str = "invalid params") -> JSONResponse:
    return a2a_error(_INVALID_PARAMS, message)


def from_agent_error(err: AgentError) -> JSONResponse:
    """Generic HTTP mapping for non-A2A surfaces (admin, console APIs)."""
    public = err.public()  # dict: {category, message, source?}
    if err.a2a_code is not None:
        return a2a_error(err.a2a_code, public["message"])
    status = _CATEGORY_HTTP.get(err.category, 500)
    return JSONResponse(status_code=status, content={"error": public})
