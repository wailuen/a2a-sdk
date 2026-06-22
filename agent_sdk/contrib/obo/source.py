"""GraphSource — a SourceAdapter that calls Microsoft Graph under OBO (DESIGN §9).

Ties the two halves together: it builds an :class:`OboExchanger` from its own
credential namespace (the confidential-client tenant/client/secret), reads the
per-request user assertion from :func:`current_assertion`, exchanges it for a
delegated Graph token, and uses that as the ``Authorization`` bearer on calls to
``graph.microsoft.com`` (host-pinned by ``SourceAdapter.allowed_hosts``).

Register it like any source — declaring the three Azure credential fields and,
optionally, the scopes via ``init_kwargs``::

    from agent_sdk.contrib.obo import GraphSource, GRAPH_CREDENTIAL_FIELDS
    from agent_sdk.contrib.obo.scopes import graph_scopes

    agent.register_source(
        GraphSource,
        credentials=GRAPH_CREDENTIAL_FIELDS,
        init_kwargs={"scopes": graph_scopes("User.Read", "Mail.Read")},
    )

A tool then receives it by annotation and calls Graph without touching tokens::

    @tools.tool()
    async def whoami(_: Empty, *, graph: GraphSource) -> dict:
        return await graph.graph_json("GET", "/me")

Subclass to pin a different ``source_name`` (and thus credential namespace) or a
non-default scope set; the OBO plumbing is inherited unchanged.
"""

from __future__ import annotations

from typing import Any

from ...credentials.fields import CredentialField
from ...models.errors import AgentError, ErrorCategory
from ...sources import CredentialResolver, SourceAdapter
from .context import current_assertion
from .exchange import OboCredentials, OboExchanger
from .scopes import DEFAULT_READ_SCOPES, GRAPH_API_V1

# The three confidential-client credentials GraphSource resolves from its own
# namespace. Field names are lowercase per CredentialField's contract; the
# console renders these. Declare them when registering (or your own equivalents).
GRAPH_CREDENTIAL_FIELDS: list[CredentialField] = [
    CredentialField(
        name="azure_tenant_id",
        label="Azure AD tenant ID",
        secret=False,
        help_text="Directory (tenant) ID — a GUID or <name>.onmicrosoft.com.",
    ),
    CredentialField(
        name="azure_client_id",
        label="Azure AD application (client) ID",
        secret=False,
        help_text="Application (client) ID of the confidential-client app registration.",
    ),
    CredentialField(
        name="azure_client_secret",
        label="Azure AD client secret",
        secret=True,
        help_text="Client secret for the confidential-client app registration.",
    ),
]


class GraphSource(SourceAdapter):
    """OBO-backed Microsoft Graph source. Pin a different namespace by
    subclassing and overriding ``source_name``."""

    source_name = "graph"
    allowed_hosts = ["graph.microsoft.com"]

    def __init__(
        self,
        settings: Any,
        credential_resolver: CredentialResolver,
        *,
        scopes: list[str] | None = None,
        expiry_buffer_seconds: int = 30,
        api_base: str = GRAPH_API_V1,
        exchanger: OboExchanger | None = None,
        expected_audiences: list[str] | None = None,
    ) -> None:
        super().__init__(settings, credential_resolver)
        self._api_base = api_base.rstrip("/")
        # `exchanger` is a test/advanced seam; normally built lazily from creds.
        self._exchanger = exchanger
        self._scopes = list(scopes) if scopes else list(DEFAULT_READ_SCOPES)
        self._expiry_buffer = expiry_buffer_seconds
        # None → OboExchanger defaults to {client_id, api://client_id}. Pass a
        # custom App ID URI here when the app registration uses one.
        self._expected_audiences = expected_audiences
        # Set by _bind_credential_store() after __init__; the exchanger is built
        # lazily so the cache is always ready before the first exchange.
        self._token_cache: Any = None

    # ── OBO plumbing ──
    def _bind_credential_store(self, store: Any, _cache_factory=None) -> None:
        """Create the persistent MSAL token cache from the SDK credential store.

        Called by build_app() after __init__; do not call from user code.

        Parameters
        ----------
        _cache_factory:
            Optional zero-argument callable injected by tests to supply a fake
            inner cache without patching module-level symbols.  Must be ``None``
            in production.
        """
        super()._bind_credential_store(store)
        from .cache import MsalTokenCache
        self._token_cache = MsalTokenCache(store, self.source_name, _cache_factory=_cache_factory)

    def _credentials_provider(self) -> OboCredentials | None:
        tenant = self.credential_or_none("azure_tenant_id")
        client = self.credential_or_none("azure_client_id")
        secret = self.credential_or_none("azure_client_secret")
        if not (tenant and client and secret):
            return None  # surfaces as AgentError(AUTH) 'not configured' in the exchanger
        return OboCredentials(tenant_id=tenant, client_id=client, client_secret=secret)

    def _get_exchanger(self) -> OboExchanger:
        if self._exchanger is None:
            self._exchanger = OboExchanger(
                credentials_provider=self._credentials_provider,
                scopes=self._scopes,
                expiry_buffer_seconds=self._expiry_buffer,
                expected_audiences=self._expected_audiences,
                token_cache=self._token_cache,  # None when used without build_app (tests)
            )
        return self._exchanger

    async def bearer(self) -> str:
        """Exchange the current request's assertion for a delegated Graph token.
        Raises ``AgentError(AUTH)`` if there is no assertion in context (the
        request did not carry an Entra user token, or the middleware is not
        installed)."""
        assertion = current_assertion()
        if not assertion:
            raise AgentError(
                ErrorCategory.AUTH,
                "no user assertion in request context — OBO requires an inbound "
                "Entra user token (and OboAssertionMiddleware installed)",
                source=self.source_name,
            )
        token = await self._get_exchanger().exchange_with_retry(assertion)
        return token.access_token

    # ── Graph calls (host-pinned, auth injected) ──
    def _graph_url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path  # caller passed an absolute URL; _check_host still gates it
        return f"{self._api_base}/{path.lstrip('/')}"

    async def graph_request(self, method: str, path: str, **kwargs: Any):
        """Call Graph with the OBO bearer injected. Host is pinned to
        graph.microsoft.com by ``allowed_hosts`` (SSRF guard inherited)."""
        url = self._graph_url(path)
        self._check_host(url)  # reject a disallowed host BEFORE minting a token
        headers = dict(kwargs.pop("headers", {}) or {})
        headers["Authorization"] = f"Bearer {await self.bearer()}"
        return await self._request(method, url, headers=headers, **kwargs)

    async def graph_json(self, method: str, path: str, **kwargs: Any) -> Any:
        """``graph_request`` + ``.json()`` decode (raises UPSTREAM on bad JSON)."""
        resp = await self.graph_request(method, path, **kwargs)
        try:
            return resp.json()
        except ValueError as exc:
            raise AgentError(
                ErrorCategory.UPSTREAM,
                f"upstream '{self.source_name}' returned a non-JSON body",
                source=self.source_name,
            ) from exc


__all__ = ["GraphSource", "GRAPH_CREDENTIAL_FIELDS"]
