"""RT-003 (redteam, high, SI-2): ``ToolInputValidationError.__init__`` must
not set its own exception message to ``str(validation_error)``.

Root cause: pydantic renders ``str(ValidationError)`` with each error's
``msg``/``input`` baked in — e.g. a custom ``@field_validator`` that raises
``ValueError(f"bad token {v!r}")`` produces a rendered string containing the
raw rejected value. GH-135's SI-2 acceptance criteria required that value
stay unreachable via a bare ``str(exc)``, but wrapping it verbatim in
``super().__init__(str(validation_error))`` armed exactly that leak for any
downstream ``except Exception as e: str(e)`` handler.

Fix: the exception's own message is now a fixed, non-interpolating string.
The raw ``pydantic.ValidationError`` stays reachable ONLY via
``.validation_error``, which ``safe_validation_message()`` (agent/loop.py)
already consumes to build a loc+type-only, redacted diagnostic.
"""

from __future__ import annotations

from pydantic import BaseModel, ValidationError, field_validator

from agent_sdk.agent.registry import ToolInputValidationError

SECRET = "sk-SUPERSECRET-123"


class _RejectingModel(BaseModel):
    token: str

    @field_validator("token")
    @classmethod
    def _reject(cls, v: str) -> str:
        raise ValueError(f"bad token {v!r}")


def _validation_error(secret: str) -> ValidationError:
    try:
        _RejectingModel(token=secret)
    except ValidationError as exc:
        return exc
    raise AssertionError("expected ValidationError")


def test_tool_input_validation_error_message_never_embeds_rejected_value():
    exc = ToolInputValidationError(_validation_error(SECRET), tool_name="my_tool")
    assert SECRET not in str(exc), (
        f"ToolInputValidationError message leaked the rejected input value: {str(exc)!r}"
    )


def test_tool_input_validation_error_message_is_fixed_non_interpolating():
    exc = ToolInputValidationError(_validation_error(SECRET), tool_name="my_tool")
    assert str(exc) == "tool 'my_tool' input validation failed", str(exc)


def test_tool_input_validation_error_still_exposes_raw_validation_error():
    ve = _validation_error(SECRET)
    exc = ToolInputValidationError(ve, tool_name="my_tool")
    assert exc.validation_error is ve
