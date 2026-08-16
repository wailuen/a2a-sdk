"""RT-009 (medium): ``ContentModel.to_plain_text``'s delimiter-safety contract
(agent_sdk/models/content_types.py) instructs every external domain-card
author to route untrusted field values through
``agent_sdk.common.redact.safe_error_text``/``safe_block_text`` before
interpolating them into a rendered string. A helper the SDK's own stable-core
contract mandates third-party subclasses depend on must itself be reachable
from — and covered by the strict-SemVer promise of — the stable public
surface (``agent_sdk``), not left on a submodule path free to change in any
minor.
"""

import agent_sdk
from agent_sdk.common.redact import (
    safe_block_text as _RedactSafeBlockText,
    safe_error_text as _RedactSafeErrorText,
)


def test_safe_error_text_importable_from_top_level() -> None:
    assert agent_sdk.safe_error_text is _RedactSafeErrorText


def test_safe_block_text_importable_from_top_level() -> None:
    assert agent_sdk.safe_block_text is _RedactSafeBlockText


def test_safe_error_text_in_all() -> None:
    assert "safe_error_text" in agent_sdk.__all__


def test_safe_block_text_in_all() -> None:
    assert "safe_block_text" in agent_sdk.__all__


# ---------------------------------------------------------------------------
# RT-002 (round-5 fresh-lens debug) — the delimiter-safety contract's helper.
#
# The two helpers above satisfy the SI-2 line-break/control contract, but NOT the
# GH-130 separator contract: safe_error_text performs no separator neutralisation
# whatsoever. Following the old §4.0 wording literally ("route untrusted values
# through safe_error_text/safe_block_text") therefore left a third-party domain
# card wide open to the `<`/`>`/`(`/`)`/`=`/`|` identity-fabrication attacks GH-130
# closed. The only implementation that discharged the contract — content_types'
# _sanitize_cell and its separator alphabet — was module-private and unexported, so
# the mandated rule was literally unsatisfiable through public API and the documented
# workaround was to hand-rebuild the alphabet per card module: the divergent second
# copy C-007 exists to prevent.
#
# safe_cell_text is that implementation, promoted into the C-007 family. These tests
# pin BOTH halves: it is public and stable, AND content_types keeps delegating to it
# rather than growing a second copy.
# ---------------------------------------------------------------------------


def test_safe_cell_text_importable_from_top_level() -> None:
    from agent_sdk.common.redact import safe_cell_text

    assert agent_sdk.safe_cell_text is safe_cell_text


def test_safe_cell_text_in_all() -> None:
    assert "safe_cell_text" in agent_sdk.__all__


def test_content_types_sanitize_cell_delegates_to_public_helper() -> None:
    """_sanitize_cell must remain a thin alias, never a second implementation.

    A divergent copy is the exact failure this promotion removed — and the one
    four consecutive review rounds proved nobody catches by hand.
    """
    from agent_sdk.common.redact import safe_cell_text
    from agent_sdk.models import content_types

    hostile = "a | b <c> (d) [e] = f, g: h @ i – j — k → l\nm n"
    assert content_types._sanitize_cell(hostile) == safe_cell_text(hostile)


def test_safe_cell_text_neutralises_what_safe_error_text_does_not() -> None:
    """The contract-relevant difference, pinned: safe_error_text is NOT a
    substitute for safe_cell_text on a delimited render.

    If this ever passes trivially (both helpers producing the same output), the
    separator alphabet has been lost and every documented "route it through
    safe_cell_text" instruction has silently become a no-op.
    """
    from agent_sdk.common.redact import safe_cell_text

    hostile = "victim> <ceo@corp.com"
    celled = safe_cell_text(hostile)
    assert agent_sdk.safe_error_text(hostile, max_len=None) != celled
    for separator in "<>()[]=|":
        assert separator not in celled, (
            f"safe_cell_text left the bare separator {separator!r} intact — a "
            "domain card using it can still have a field boundary fabricated."
        )
