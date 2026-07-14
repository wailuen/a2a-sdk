"""RT G-A-002 (w000 group A): decrypt() must not swallow VM-level exceptions."""

from __future__ import annotations

import pytest

from agent_sdk.credentials.crypto import decrypt
from agent_sdk.models.errors import AgentError, ErrorCategory


class _RaisingAES:
    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    def decrypt(self, nonce: bytes, ct: bytes, aad: bytes) -> bytes:
        raise self._exc


def test_decrypt_wraps_value_error_as_agent_error() -> None:
    aes = _RaisingAES(ValueError("nonce too short"))
    with pytest.raises(AgentError) as exc_info:
        decrypt(aes, "ns", "field", b"AAAAAAAAAAAAAAAA")
    assert exc_info.value.category == ErrorCategory.INTERNAL
    assert exc_info.value.message == "credential store decryption failed"


def test_decrypt_does_not_swallow_memory_error() -> None:
    aes = _RaisingAES(MemoryError("simulated OOM"))
    with pytest.raises(MemoryError):
        decrypt(aes, "ns", "field", b"AAAAAAAAAAAAAAAA")


def test_decrypt_does_not_swallow_recursion_error() -> None:
    aes = _RaisingAES(RecursionError("simulated stack overflow"))
    with pytest.raises(RecursionError):
        decrypt(aes, "ns", "field", b"AAAAAAAAAAAAAAAA")
