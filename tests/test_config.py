import pytest
from pydantic import ValidationError
from pydantic_settings import SettingsConfigDict

from agent_sdk.config import BaseAgentSettings

MARKER = "ZQXJmarkerSECRETvalue0123456789TAILXYZ"


def _env(monkeypatch):
    monkeypatch.setenv("MASTER_KEY", MARKER)
    monkeypatch.setenv("DEV_MODE", "false")
    monkeypatch.delenv("PUBLIC_URL", raising=False)


def _assert_clean(exc: ValidationError) -> None:
    text = str(exc)
    assert "PUBLIC_URL" in text
    assert "input_value" not in text
    assert MARKER not in text
    assert MARKER[:8] not in text
    assert MARKER[-8:] not in text


def test_model_validator_error_hides_input(monkeypatch):
    _env(monkeypatch)
    with pytest.raises(ValidationError) as ei:
        BaseAgentSettings(_env_file=None)
    _assert_clean(ei.value)


def test_subclass_overriding_model_config_still_hides_input(monkeypatch):
    _env(monkeypatch)

    class Sub(BaseAgentSettings):
        model_config = SettingsConfigDict(env_file=None, extra="ignore")

    with pytest.raises(ValidationError) as ei:
        Sub()
    _assert_clean(ei.value)


def test_hide_input_flag_set():
    assert BaseAgentSettings.model_config["hide_input_in_errors"] is True
