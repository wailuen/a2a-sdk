"""Discovery surfaces for per-call credential forwarding.

A client must learn that it MAY send the ``X-Agent-Credentials`` header and
what envelope to put in it. Two conformant channels (a2a-advisor pass):

- A2A: a non-auth ``AgentExtension`` in ``capabilities.extensions[]`` — the
  spec-sanctioned, machine-readable discovery path. NOT a ``securityScheme``:
  the vendor key is a per-tenant credential carried ON TOP of the agent's own
  bearer auth, not the thing that authenticates the agent.
- MCP: human-readable ``instructions`` on the ``initialize`` result, which
  Claude.ai injects into model context (the only reliable channel there).

Both are built from the SAME registered-source field declarations, so they
never drift. Only field NAMES are ever surfaced — never values (secrets
hygiene). When no source declares credentials, both builders return ``None``
and neither surface mentions forwarding.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ..models.a2a import AgentExtension
from .fields import CredentialField
from .forwarding import HEADER_NAME

EXTENSION_URI = "https://agent-sdk.dev/extensions/credential-forwarding/v1"

_CredFields = Mapping[str, Sequence[CredentialField]]


def credential_sources_map(credential_fields: _CredFields) -> dict[str, list[str]]:
    """``{source_name: [field_name, ...]}`` for sources that declare any
    credentials. Field names only — the resolver/store hold the values."""
    return {
        source: [f.name for f in fields]
        for source, fields in credential_fields.items()
        if fields
    }


def forwarding_instructions(credential_fields: _CredFields) -> str | None:
    """Human-readable ``initialize.instructions`` text, or None when no source
    declares credentials.

    Phrased as AMBIENT operator context, not an action directive: Claude.ai
    injects this into MODEL context, and the model cannot set request headers.
    So it must not read as "send the header" (the model would try to relay an
    impossible action). The machine-readable envelope/encoding for a
    programmatic client lives in the AgentCard extension ``params`` instead.
    """
    sources = credential_sources_map(credential_fields)
    if not sources:
        return None
    catalogue = "; ".join(f"{name}: {', '.join(fields)}" for name, fields in sources.items())
    return (
        "This server uses vendor API credentials configured by the operator "
        f"(recognized sources and fields — {catalogue}). A calling client may "
        f"also forward them per request via the {HEADER_NAME} header; you do not "
        "set these yourself. If a tool reports a configuration or authentication "
        "error, the credential is unavailable — ask the user to configure it "
        "rather than retrying. Credential values are never logged or echoed."
    )


def credential_forwarding_extension(
    credential_fields: _CredFields,
) -> AgentExtension | None:
    """Machine-readable AgentCard extension, or None when no source declares
    credentials. ``required=False`` — a client that ignores it falls back to
    the store, which is exactly today's behavior."""
    sources = credential_sources_map(credential_fields)
    if not sources:
        return None
    return AgentExtension(
        uri=EXTENSION_URI,
        description=(
            f"Per-call vendor credentials forwarded via the {HEADER_NAME} header "
            "(base64-encoded JSON envelope). Optional; falls back to server-stored "
            "credentials when absent."
        ),
        required=False,
        params={
            "header": HEADER_NAME,
            "encoding": "base64(json)",
            "sources": sources,
            "schema": {
                "type": "object",
                "additionalProperties": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                },
            },
        },
    )
