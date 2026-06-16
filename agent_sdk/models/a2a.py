"""A2A v0.3.0 wire shapes (HTTP+JSON transport) — DESIGN.md §5.1.

Rules baked in here:
- Parts discriminate on ``kind``, never ``type``.
- ``TaskStatus`` serializes to ``{state, message?, timestamp?, error?}``; anything
  the SDK tracks internally lives outside these models.
- Server-emitted ``contextId`` is always a non-empty UUID (enforced by the
  task store, not by the model).
- All wire field names are camelCase; Python attributes are aliased.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .errors import WireError


class _Wire(BaseModel):
    """Base for wire models: camelCase aliases, emit by alias, drop None."""

    model_config = ConfigDict(populate_by_name=True)

    def wire(self) -> dict:
        return self.model_dump(by_alias=True, exclude_none=True)


# ── Parts ──────────────────────────────────────────────────────────────────


class TextPart(_Wire):
    kind: Literal["text"] = "text"
    text: str
    metadata: dict[str, Any] | None = None


class FileWithBytes(_Wire):
    name: str | None = None
    mime_type: str | None = Field(default=None, alias="mimeType")
    bytes: str  # base64


class FileWithUri(_Wire):
    name: str | None = None
    mime_type: str | None = Field(default=None, alias="mimeType")
    uri: str


class FilePart(_Wire):
    kind: Literal["file"] = "file"
    file: FileWithBytes | FileWithUri
    metadata: dict[str, Any] | None = None

    @model_validator(mode="before")
    @classmethod
    def _file_xor(cls, values: Any) -> Any:
        f = values.get("file") if isinstance(values, dict) else None
        if isinstance(f, dict) and "bytes" in f and "uri" in f:
            raise ValueError("FilePart.file must have bytes XOR uri, not both")
        return values


class DataPart(_Wire):
    kind: Literal["data"] = "data"
    data: dict[str, Any] | list[Any]
    metadata: dict[str, Any] | None = None


Part = Annotated[Union[TextPart, FilePart, DataPart], Field(discriminator="kind")]


# ── Message / Task ─────────────────────────────────────────────────────────


class Message(_Wire):
    kind: Literal["message"] = "message"
    role: Literal["user", "agent"]
    parts: list[Part] = Field(min_length=1)
    message_id: str = Field(alias="messageId")  # REQUIRED inbound (DESIGN §5.1)
    task_id: str | None = Field(default=None, alias="taskId")
    context_id: str | None = Field(default=None, alias="contextId")
    metadata: dict[str, Any] | None = None
    extensions: list[str] | None = None


class TaskState(StrEnum):
    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input-required"
    AUTH_REQUIRED = "auth-required"
    COMPLETED = "completed"
    CANCELED = "canceled"
    FAILED = "failed"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


TERMINAL_STATES = frozenset(
    {TaskState.COMPLETED, TaskState.CANCELED, TaskState.FAILED, TaskState.REJECTED}
)
INTERRUPT_STATES = frozenset({TaskState.INPUT_REQUIRED, TaskState.AUTH_REQUIRED})


class TaskStatus(_Wire):
    state: TaskState
    message: Message | None = None
    timestamp: str | None = None
    error: WireError | None = None


class Artifact(_Wire):
    artifact_id: str = Field(alias="artifactId")
    name: str | None = None
    description: str | None = None
    parts: list[Part]
    metadata: dict[str, Any] | None = None
    extensions: list[str] | None = None


class Task(_Wire):
    kind: Literal["task"] = "task"
    id: str
    context_id: str = Field(alias="contextId")
    status: TaskStatus
    artifacts: list[Artifact] | None = None
    history: list[Message] | None = None
    metadata: dict[str, Any] | None = None


# ── Streaming events ───────────────────────────────────────────────────────


class TaskStatusUpdateEvent(_Wire):
    kind: Literal["status-update"] = "status-update"
    task_id: str = Field(alias="taskId")
    context_id: str = Field(alias="contextId")
    status: TaskStatus
    final: bool = False
    metadata: dict[str, Any] | None = None


class TaskArtifactUpdateEvent(_Wire):
    kind: Literal["artifact-update"] = "artifact-update"
    task_id: str = Field(alias="taskId")
    context_id: str = Field(alias="contextId")
    artifact: Artifact
    # Optional per spec; omitted when None. We never emit a partial chunk, so
    # the emit site sets last_chunk=True and leaves append unset (== false).
    append: bool | None = None
    last_chunk: bool | None = Field(default=None, alias="lastChunk")
    metadata: dict[str, Any] | None = None


# ── message/send params ────────────────────────────────────────────────────


class PushNotificationConfig(_Wire):
    id: str | None = None
    url: str
    token: str | None = None
    authentication: dict[str, Any] | None = None


class MessageSendConfiguration(_Wire):
    """Typed configuration — never a raw dict (DESIGN §5.1)."""

    accepted_output_modes: list[str] | None = Field(
        default=None, alias="acceptedOutputModes"
    )
    history_length: int | None = Field(default=None, alias="historyLength")
    push_notification_config: PushNotificationConfig | None = Field(
        default=None, alias="pushNotificationConfig"
    )
    blocking: bool | None = None


class MessageSendParams(_Wire):
    message: Message
    configuration: MessageSendConfiguration | None = None
    metadata: dict[str, Any] | None = None


# ── Agent card ─────────────────────────────────────────────────────────────


class AgentInterface(_Wire):
    # v0.3.0 additionalInterfaces entries: BOTH fields required (DESIGN §4.5).
    transport: Literal["JSONRPC", "GRPC", "HTTP+JSON"]
    url: str


class AgentExtension(_Wire):
    uri: str
    description: str | None = None
    required: bool | None = None
    params: dict[str, Any] | None = None


class AgentCapabilities(_Wire):
    streaming: bool = True
    push_notifications: bool = Field(default=False, alias="pushNotifications")
    state_transition_history: bool = Field(default=False, alias="stateTransitionHistory")
    extensions: list[AgentExtension] | None = None


class AgentSkill(_Wire):
    """Spec fields only; SDK extras ride under the x-sdk namespace (DESIGN §4.5)."""

    id: str
    name: str
    description: str
    tags: list[str] = Field(default_factory=list)
    examples: list[str] | None = None
    input_modes: list[str] | None = Field(default=None, alias="inputModes")
    output_modes: list[str] | None = Field(default=None, alias="outputModes")
    security: list[dict[str, list[str]]] | None = None
    x_sdk: dict[str, Any] | None = Field(default=None, alias="x-sdk")


class AgentProvider(_Wire):
    organization: str
    url: str  # REQUIRED by v0.3.0 when provider is present


class AgentCard(_Wire):
    protocol_version: str = Field(default="0.3.0", alias="protocolVersion")
    name: str
    description: str
    url: str  # REQUIRED — never omitted; dev falls back to localhost (DESIGN §4.5)
    preferred_transport: Literal["JSONRPC", "GRPC", "HTTP+JSON"] = Field(default="HTTP+JSON", alias="preferredTransport")
    additional_interfaces: list[AgentInterface] | None = Field(
        default=None, alias="additionalInterfaces"
    )
    version: str
    provider: AgentProvider | None = None
    capabilities: AgentCapabilities = Field(default_factory=AgentCapabilities)
    default_input_modes: list[str] = Field(
        default_factory=lambda: ["text/plain"], alias="defaultInputModes"
    )
    default_output_modes: list[str] = Field(
        default_factory=lambda: ["text/plain", "application/json"],
        alias="defaultOutputModes",
    )
    skills: list[AgentSkill] = Field(default_factory=list)
    supports_authenticated_extended_card: bool = Field(
        default=False, alias="supportsAuthenticatedExtendedCard"
    )
    security_schemes: dict[str, Any] | None = Field(
        default=None, alias="securitySchemes"
    )
    security: list[dict[str, list[str]]] | None = None
    x_agui: dict[str, Any] | None = Field(default=None, alias="x-agui")

    @model_validator(mode="after")
    def _interfaces_complete(self) -> "AgentCard":
        for iface in self.additional_interfaces or []:
            if not iface.transport or not iface.url:
                raise ValueError("additionalInterfaces entries require transport AND url")
        return self
