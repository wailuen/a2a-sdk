"""CredentialStore interface + namespace rules (DESIGN.md §6).

Store keys are ``{namespace}/{field}``. Source adapters resolve only their
own ``source_name`` namespace; reserved namespaces (auth material, Bedrock
credentials) are unreachable from any adapter resolver.
"""

from __future__ import annotations

import abc

from ..sources import CredentialResolver
from .forwarding import lookup as _forwarded_lookup

# Reserved namespaces: persisted auth material + model credentials. No
# adapter resolver can read these.
NS_API_KEYS = "__api_keys__"
NS_OAUTH_CLIENTS = "__oauth_clients__"
NS_OAUTH_REFRESH = "__oauth_refresh__"
NS_BEDROCK = "__bedrock__"
# LLM model-backend API keys (OpenAI, Azure OpenAI, Anthropic). Seeded via
# /admin → Model Backend. The agent reads from this namespace at startup to
# construct the model client — no key ever lives in .env.
NS_MODEL = "__model__"

RESERVED_NAMESPACES = frozenset(
    {NS_API_KEYS, NS_OAUTH_CLIENTS, NS_OAUTH_REFRESH, NS_BEDROCK, NS_MODEL, "__meta__"}
)


class CredentialStore(abc.ABC):
    @abc.abstractmethod
    def get(self, namespace: str, field: str) -> str | None: ...

    @abc.abstractmethod
    def set(self, namespace: str, field: str, value: str) -> None: ...

    @abc.abstractmethod
    def delete(self, namespace: str, field: str) -> None: ...

    @abc.abstractmethod
    def list_fields(self, namespace: str) -> list[str]: ...

    @abc.abstractmethod
    def close(self) -> None: ...


def resolver_for_source(store: CredentialStore, source_name: str) -> CredentialResolver:
    """Per-adapter resolver: bound to one namespace, reserved names refused.
    The adapter's claimed namespace argument is ignored in favor of the
    bound one — an adapter cannot read outside its own namespace even if it
    passes a different name.

    A per-request forwarded credential (``X-Agent-Credentials``, see
    :mod:`.forwarding`) takes priority over the store; an empty request context
    falls through to the stored value (non-breaking). Reserved namespaces never
    reach this layering — they raise below before any resolver is built."""
    if source_name in RESERVED_NAMESPACES:
        raise ValueError(f"{source_name!r} is a reserved namespace")

    def resolve(_namespace: str, field: str) -> str | None:
        forwarded = _forwarded_lookup(source_name, field)
        if forwarded is not None:
            return forwarded
        return store.get(source_name, field)

    return resolve
