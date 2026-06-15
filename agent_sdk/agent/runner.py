"""Task worker — bridges loop events to A2A task state (DESIGN.md §5.1/§5.2).

One worker per task, regardless of which protocol started it. It is the only
writer of the task record: it folds loop events into the canonical A2A
``Task`` (status, history, artifacts) and publishes ``StreamItem``s to the
record's subscribers. Each item carries the pre-built A2A wire frame (used by
A2A SSE consumers as-is) AND the raw loop event (mapped by the AG-UI route's
per-request state machine) — interrupts therefore resume identically across
protocols.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

from ..a2ui.translator import A2uiCapabilities, translate
from ..models.a2a import (
    Artifact,
    DataPart,
    Message,
    Task,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TextPart,
)
from ..models.content_types import A2UI_MIME_TYPE, ContentModel
from ..models.errors import AgentError, ErrorCategory
from ..tasks.store import TaskRecord, TaskStore
from .events import (
    ArtifactEvent,
    DoneEvent,
    InterruptEvent,
    NoteEvent,
    ProgressEvent,
    TextEvent,
    UsageEvent,
)
from .loop import LoopPolicies, run_loop
from .model_client import ModelClient
from .registry import ToolRegistry
from .skills import SkillsRegistry
from ..sources import SourceAdapter


@dataclass(slots=True)
class StreamItem:
    frame: dict[str, Any] | None  # A2A wire frame, ready to send
    event: Any  # raw loop event (AG-UI mapping) — None for synthetic frames
    final: bool = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _agent_message(
    record: TaskRecord, text: str, metadata: dict[str, Any] | None = None
) -> Message:
    return Message(
        role="agent",
        parts=[TextPart(text=text)],
        messageId=uuid.uuid4().hex,
        taskId=record.task.id,
        contextId=record.task.context_id,
        metadata=metadata,
    )


def _status_frame(record: TaskRecord, *, final: bool = False) -> dict[str, Any]:
    return TaskStatusUpdateEvent(
        taskId=record.task.id,
        contextId=record.task.context_id,
        status=record.task.status,
        final=final,
    ).wire()


def _set_status(
    record: TaskRecord, state: TaskState, message: Message | None = None
) -> None:
    record.task.status = TaskStatus(state=state, message=message, timestamp=_now())


def _validate_a2ui_wire(payload: "ContentModel", a2ui_messages: list[Any]) -> None:
    """SC-D1: Structural assertion on translate() output + domain-card wire() value.

    Standard Profile types use _Wire.wire() (Pydantic-validated), so this
    primarily catches domain cards whose wire() returns a non-conformant value.
    Raises ValueError before delivery rather than silently sending malformed data.
    """
    from ..models.content_types import CATALOG_ID as _CATALOG_ID  # local to avoid circulars

    cls = type(payload)
    label = f"{cls.__name__!r} ({payload.data_type!r})"

    # Structural assertion on the a2ui_messages list itself.
    if not (isinstance(a2ui_messages, list) and len(a2ui_messages) > 0):
        raise ValueError(
            f"Content type {label}: translate() must return a non-empty list of dicts; "
            f"got {type(a2ui_messages).__name__!r}"
        )
    if not all(isinstance(m, dict) and "version" in m for m in a2ui_messages):
        raise ValueError(
            f"Content type {label}: each A2UI message must be a dict with a 'version' key; "
            f"malformed translate() output detected"
        )

    # For domain cards (non-standard-catalog types): also validate wire() output
    # directly. Standard Profile types are Pydantic-validated so wire() is safe.
    if cls.catalog_id != _CATALOG_ID:
        try:
            wire_val = payload.wire()
        except Exception as exc:
            raise ValueError(
                f"Domain card {label}: wire() raised an exception: {exc}"
            ) from exc
        if not isinstance(wire_val, dict) or not wire_val:
            raise ValueError(
                f"Domain card {label}: wire() must return a non-empty dict; "
                f"got {type(wire_val).__name__!r}: {wire_val!r}"
            )


def build_artifact(
    event: ArtifactEvent, capabilities: A2uiCapabilities
) -> Artifact:
    """Dual-part structured artifact: TextPart fallback + DataPart payload (§5.1).
    ContentModel payloads always emit both parts. When the A2UI capability is
    active the DataPart carries the A2UI message array; when inactive it carries
    the raw model dump so plain A2A clients can extract structured data without
    parsing the TextPart (A2A §D3). Non-ContentModel BaseModel and plain-value
    payloads follow the same dual-part contract."""
    payload = event.model
    metadata: dict[str, Any] = {"data_type": event.data_type, "tool_name": event.tool_name}
    if isinstance(payload, ContentModel):
        parts: list[Any] = [TextPart(text=payload.to_plain_text())]
        a2ui_messages = translate(payload, capabilities=capabilities)
        if a2ui_messages is not None:
            # SC-D1: validate structure before delivery
            _validate_a2ui_wire(payload, a2ui_messages)
            metadata["mimeType"] = A2UI_MIME_TYPE
            # A2UI delivery: DataPart.data is the bare message array (trap #11),
            # and the part is self-describing via its mimeType.
            parts.append(
                DataPart(data=a2ui_messages, metadata={"mimeType": A2UI_MIME_TYPE})
            )
        else:
            # P6-02 / A2A §D3: always emit a DataPart for structured payloads,
            # even when A2UI is not active, so plain A2A clients can consume
            # the model dump without screen-scraping the TextPart fallback.
            dump = payload.model_dump(mode="json", by_alias=True, exclude_none=True)
            parts.append(
                DataPart(
                    data=dump,
                    metadata={"data_type": event.data_type, "tool_name": event.tool_name},
                )
            )
    elif isinstance(payload, BaseModel):
        dump = payload.model_dump(mode="json", by_alias=True, exclude_none=True)
        parts = [
            TextPart(text=str(dump)),
            DataPart(data=dump, metadata=dict(metadata)),
        ]
    else:
        # SC-A2: plain scalar — emit TextPart fallback + DataPart so plain A2A
        # clients can extract structured data without screen-scraping (A2A §D3).
        parts = [
            TextPart(text=str(payload)),
            DataPart(
                kind="data",
                data={"value": payload},
                metadata={"mimeType": "application/json"},
            ),
        ]
    return Artifact(
        artifactId=uuid.uuid4().hex,
        name=event.data_type,
        parts=parts,
        metadata=metadata,
    )


async def run_task_worker(
    *,
    store: TaskStore,
    record: TaskRecord,
    model: ModelClient,
    registry: ToolRegistry,
    adapters: dict[type[SourceAdapter], SourceAdapter],
    skills: SkillsRegistry | None,
    system: str,
    capabilities: A2uiCapabilities,
    policies: LoopPolicies,
) -> None:
    """Consume the loop until DoneEvent or interrupt-expiry/cancellation.
    ``record.messages`` must already contain the folded user turn."""
    task = record.task
    text_segments: list[str] = []

    async def wait_resume(interrupt_id: str) -> Any:
        # the InterruptEvent handler below registered the future already
        future = record.resume_future
        if future is None:  # defensive: interrupt registration failed
            raise AgentError(ErrorCategory.INTERNAL, "resume channel missing")
        return await future

    def publish(frame: dict[str, Any] | None, event: Any, *, final: bool = False) -> None:
        store.publish(task.id, StreamItem(frame=frame, event=event, final=final))

    try:
        _set_status(record, TaskState.WORKING)
        publish(_status_frame(record), None)

        async for event in run_loop(
            model=model,
            registry=registry,
            adapters=adapters,
            system=system,
            messages=record.messages,
            skills=skills,
            policies=policies,
            wait_resume=wait_resume,
            spent_tokens=record.spent_tokens,
        ):
            if isinstance(event, UsageEvent):
                record.spent_tokens += event.input_tokens + event.output_tokens
                publish(None, event)
            elif isinstance(event, TextEvent):
                text_segments.append(event.text)
                _set_status(record, TaskState.WORKING, _agent_message(record, event.text))
                publish(_status_frame(record), event)
            elif isinstance(event, (ProgressEvent, NoteEvent)):
                text = event.message if isinstance(event, ProgressEvent) else event.note
                _set_status(record, TaskState.WORKING, _agent_message(record, text))
                publish(_status_frame(record), event)
            elif isinstance(event, ArtifactEvent):
                artifact = build_artifact(event, capabilities)
                task.artifacts = (task.artifacts or []) + [artifact]
                frame = TaskArtifactUpdateEvent(
                    taskId=task.id,
                    contextId=task.context_id,
                    artifact=artifact,
                    lastChunk=True,
                ).wire()
                publish(frame, event)
            elif isinstance(event, InterruptEvent):
                # cap check + resume-channel registration; at the cap this
                # raises and becomes a typed task failure (§5.2)
                store.mark_interrupted(task.id, event.interrupt_id)
                state = (
                    TaskState.AUTH_REQUIRED
                    if "auth" in event.reason
                    else TaskState.INPUT_REQUIRED
                )
                _set_status(
                    record,
                    state,
                    _agent_message(
                        record,
                        event.message,
                        metadata={
                            "interruptId": event.interrupt_id,
                            "responseSchema": event.response_schema,
                            "toolCallId": event.tool_call_id,
                        },
                    ),
                )
                # the stream MAY close final:true while interrupted (§5.1)
                publish(_status_frame(record, final=True), event, final=True)
            elif isinstance(event, DoneEvent):
                if event.ok:
                    final_text = "\n\n".join(s for s in text_segments if s).strip()
                    message = _agent_message(record, final_text) if final_text else None
                    if message is not None:
                        task.history = (task.history or []) + [message]
                    _set_status(record, TaskState.COMPLETED, message)
                else:
                    _set_status(
                        record,
                        TaskState.FAILED,
                        _agent_message(record, event.error or "task failed"),
                    )
                publish(_status_frame(record, final=True), event, final=True)
            else:
                # TurnStarted / ToolCall / ToolResult: no A2A frame; AG-UI
                # consumers map these to STEP_* and tool-call families
                publish(None, event)

    except asyncio.CancelledError:
        # cancel/eviction path: the canceller owns status + final frame +
        # stream closure
        raise
    except AgentError as err:
        _set_status(record, TaskState.FAILED, _agent_message(record, err.message))
        publish(_status_frame(record, final=True), DoneEvent(ok=False, error=err.message), final=True)
        store.close_streams(task.id)
    except Exception:
        _set_status(record, TaskState.FAILED, _agent_message(record, "internal error"))
        publish(_status_frame(record, final=True), DoneEvent(ok=False, error="internal error"), final=True)
        store.close_streams(task.id)
    else:
        store.close_streams(task.id)


def new_task(context_id: str | None = None) -> Task:
    return Task(
        id=uuid.uuid4().hex,
        contextId=context_id or uuid.uuid4().hex,
        status=TaskStatus(state=TaskState.SUBMITTED, timestamp=_now()),
        history=[],
        artifacts=[],
    )
