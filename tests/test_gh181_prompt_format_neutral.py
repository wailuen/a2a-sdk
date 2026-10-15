from agent_sdk.a2ui.catalog import get_system_prompt_section


def _section() -> str:
    text = get_system_prompt_section()
    assert text
    return text


def test_section_does_not_dictate_prose() -> None:
    assert "prose" not in _section().split("Components tools can emit")[0]


def test_section_defers_format_to_agent_instructions() -> None:
    head = _section().split("Components tools can emit")[0]
    assert "Summarise tool results for the user in the format your instructions ask for" in head


def test_cards_delivered_automatically() -> None:
    assert "deliver these A2UI cards to the user automatically" in _section()


def test_never_write_component_json() -> None:
    assert "Do not write component JSON in your reply" in _section()


def test_only_values_tools_returned() -> None:
    assert "using only values the tools returned" in _section()


def test_market_briefing_prose_exception_unchanged() -> None:
    text = _section()
    if "MarketBriefing" in text:
        assert "[prose card" in text
