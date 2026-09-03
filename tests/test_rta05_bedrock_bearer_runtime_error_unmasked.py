"""RT-A05 / RT-005: the botocore version-floor failure must reach the operator,
and nothing else may ride out on the same escape hatch.

RT-A05 (original): ``converse()``'s broad ``except Exception`` masked the
actionable error from ``require_bearer_auth_botocore()``. That check runs
inside ``_boto_client()``, which is called from inside ``converse()``'s try
block (via ``loop.run_in_executor``), so the broad handler rewrote it into
``AgentError(UPSTREAM, "model invocation failed")`` -- the operator got a 502
and ``error_type=RuntimeError`` in the log, never the "upgrade boto3>=1.39"
instruction. This is LRN-104's Layer-3 rule ("never mask install/version
errors") applied to a version-floor failure, not just ``ModuleNotFoundError``.

RT-005 (round 4) closed two gaps the original fix left open:

1. Re-raising alone delivered NOTHING. The escaping exception is not an
   ``AgentError``, so ``run_loop`` (which catches only ``AgentError``) does not
   handle it and it lands in ``run_task_worker``'s generic handler, which logs
   ``type(exc).__name__`` with no message and no ``exc_info`` and maps the wire
   response to the fixed literal "internal error". The "upgrade boto3>=1.39"
   string reached neither the log nor the wire; the only observable change from
   the original fix was 502 UPSTREAM becoming 500 internal error. ``converse()``
   now LOGS the instruction at the re-raise point, which is the last place that
   still holds it.

2. ``except RuntimeError: raise`` was unconditional, so every unrelated
   ``RuntimeError`` (boto3's, or the executor's "cannot schedule new futures
   after shutdown") also escaped as a non-``AgentError`` and bypassed
   ``run_loop``'s ``AgentError`` -> ``DoneEvent`` path. The catch is now the
   dedicated ``BedrockBearerAuthUnsupported`` class only.

RT-005 (round 5) closes a THIRD gap: every test above asserts only at the
``converse()`` boundary (calling the client method directly). That is not
proof the instruction survives the real system for two independent reasons:
``agent_sdk.observability.logging.configure_logging()`` sets
``propagate = False`` on the ``agent_sdk`` root logger the first time any
test in the process builds an app (see conftest.py's ``sdk_caplog``
docstring) — after that, a bare ``caplog.at_level(...)`` assertion against an
``agent_sdk.*`` logger can read empty at full-suite scope regardless of
whether the log line fired, because it never reaches the stdlib root logger
plain ``caplog`` listens on; and nothing above ever exercises
``run_task_worker`` itself, the actual caller in a running agent process.
``test_bearer_auth_upgrade_instruction_reaches_operator_log_through_real_task_worker``
below drives a real ``BedrockModelClient`` through the real
``run_task_worker`` (only the boto3 boundary inside ``_boto_client`` is stood
in for, exactly as test_rt004_bedrock_rate_limit_and_startup_probe.py does)
and asserts via the SDK-aware ``sdk_caplog`` fixture that the instruction
reached an operator-visible log record, while the task still fails cleanly
with the fixed, generic wire text (RT-006 — no upstream detail disclosed to
the caller).
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from agent_sdk.a2ui.translator import A2uiCapabilities
from agent_sdk.agent.bedrock import BedrockBearerAuthUnsupported, BedrockModelClient
from agent_sdk.agent.loop import LoopPolicies
from agent_sdk.agent.registry import ToolRegistry
from agent_sdk.agent.runner import new_task, run_task_worker
from agent_sdk.auth.identity import Identity
from agent_sdk.models.a2a import TaskState
from agent_sdk.models.errors import AgentError, ErrorCategory
from agent_sdk.tasks.memory import InMemoryTaskStore


def _client(**kwargs):
    return BedrockModelClient(
        region="us-east-1",
        model_arn="arn:aws:bedrock:us-east-1::foundation-model/test",
        **kwargs,
    )


_IDENTITY = Identity(kind="api_key", subject="test-runner", admin=True)
_CAPABILITIES = A2uiCapabilities(tier="none", catalogs=[])
_EMPTY_REGISTRY = ToolRegistry([], {})


def _old_botocore_client() -> BedrockModelClient:
    """A BedrockModelClient whose boto3 boundary fails exactly like an
    installed-but-too-old botocore would -- no mock/patch of SDK internals,
    only the boto3 boundary (mirrors test_rt004's ``_converse_raising``)."""
    client = _client(bearer_token="tok-old-botocore")

    def _boom() -> None:
        raise BedrockBearerAuthUnsupported(
            "Bedrock bearer-token auth requires botocore>=1.39; "
            "upgrade boto3>=1.39 in your project dependencies."
        )

    client._boto_client = _boom  # type: ignore[method-assign]
    return client


def test_converse_propagates_bearer_auth_error_unmasked(monkeypatch):
    import botocore.tokens

    monkeypatch.delattr(botocore.tokens, "ScopedEnvTokenProvider", raising=False)

    client = _client(bearer_token="tok-old-botocore")

    with pytest.raises(BedrockBearerAuthUnsupported, match="botocore>=1.39") as excinfo:
        asyncio.run(client.converse(system="s", messages=[], tools=[]))

    # Still a RuntimeError subclass, so app.py's Layer-2 startup probe and any
    # caller catching RuntimeError around it are unaffected...
    assert issubclass(excinfo.type, RuntimeError)
    # ...and still never folded into the generic upstream AgentError.
    assert not issubclass(excinfo.type, AgentError)


def test_bearer_auth_error_upgrade_instruction_reaches_operator_log(monkeypatch, caplog):
    """RT-005: the actionable text must be logged where an operator can see it.

    Nothing downstream will do it: the generic ``run_task_worker`` handler that
    ultimately catches this logs only ``type(exc).__name__``, and the wire
    message is a fixed literal. If this assertion fails, the "upgrade" hint is
    reaching no one, however faithfully converse() re-raises it.
    """
    import botocore.tokens

    monkeypatch.delattr(botocore.tokens, "ScopedEnvTokenProvider", raising=False)

    client = _client(bearer_token="tok-old-botocore")

    with caplog.at_level(logging.ERROR, logger="agent_sdk.agent.bedrock"):
        with pytest.raises(BedrockBearerAuthUnsupported):
            asyncio.run(client.converse(system="s", messages=[], tools=[]))

    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "botocore>=1.39" in logged, (
        f"the upgrade instruction never reached an operator log; got {logged!r}"
    )


def test_unrelated_runtime_error_still_maps_to_agent_error(monkeypatch):
    """RT-005: the escape hatch is scoped to the version-floor failure ONLY.

    A ``RuntimeError`` from boto3 or from the bounded executor (e.g. "cannot
    schedule new futures after shutdown" after ``shutdown()``) must stay on the
    normal ``AgentError`` path so ``run_loop`` turns it into a clean
    ``DoneEvent``, instead of escaping past ``run_loop`` entirely.
    """
    client = _client()

    def _boom():
        raise RuntimeError("cannot schedule new futures after interpreter shutdown")

    monkeypatch.setattr(client, "_boto_client", _boom)

    with pytest.raises(AgentError) as excinfo:
        asyncio.run(client.converse(system="s", messages=[], tools=[]))

    assert excinfo.value.category is ErrorCategory.UPSTREAM
    assert excinfo.value.message == "model invocation failed"
    # SI-2: the botocore/executor text never reaches the wire message.
    assert "shutdown" not in excinfo.value.message


@pytest.mark.asyncio
async def test_bearer_auth_upgrade_instruction_reaches_operator_log_through_real_task_worker(
    sdk_caplog,
) -> None:
    """RT-005 (round 5): the same proof as
    ``test_bearer_auth_error_upgrade_instruction_reaches_operator_log`` above,
    but through the real ``run_task_worker`` rather than a direct
    ``converse()`` call, and via ``sdk_caplog`` rather than bare ``caplog`` --
    the boundary an operator's process actually runs, and the fixture immune
    to the ``agent_sdk`` root logger's ``propagate = False``."""
    store = InMemoryTaskStore()
    record = store.create(new_task(), _IDENTITY)
    record.messages.append({"role": "user", "content": [{"text": "hi"}]})
    task_id = record.task.id

    with sdk_caplog("agent_sdk.agent.bedrock", logging.ERROR) as records:
        await run_task_worker(
            store=store,
            record=record,
            model=_old_botocore_client(),
            registry=_EMPTY_REGISTRY,
            adapters={},
            skills=None,
            system="test system prompt",
            capabilities=_CAPABILITIES,
            policies=LoopPolicies(),
        )

    logged = "\n".join(r.getMessage() for r in records)
    assert "botocore>=1.39" in logged, (
        "the upgrade instruction never reached an operator log through the "
        f"real task worker path; got {logged!r}"
    )

    final = store.get(task_id)
    assert final is not None
    assert final.task.status.state == TaskState.FAILED, final.task.status.state

    # RT-006: the wire-facing text stays the fixed, generic literal -- the
    # real upstream detail reached the operator log above, never the caller.
    wire_error = final.task.status.error
    assert wire_error is not None
    assert wire_error.message == "internal error"
    agent_message = final.task.status.message
    assert agent_message is not None
    wire_text = "\n".join(p.text for p in agent_message.parts if hasattr(p, "text"))
    assert "botocore" not in wire_text
    assert "1.39" not in wire_text
