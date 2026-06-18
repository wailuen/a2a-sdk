"""azure_utils — lazy availability guard for the ``azure`` optional extra.

Azure backends must call :func:`require_azure_packages` at the top of their
``__init__`` (not at module import time) so that the SDK can be imported
without the Azure packages installed.

Usage in an Azure backend ``__init__``::

    from agent_sdk.contrib.azure_utils import require_azure_packages

    def __init__(self, ...):
        require_azure_packages()
        ...

Install the extra with::

    pip install agent-sdk[azure]

.. note:: Planned callers (not yet implemented)
   This utility is reserved for the following backends that are on the SDK
   roadmap but have not been built yet:

   - ``AzureTableTaskStore``   — task persistence backed by Azure Table Storage
   - ``AzureTableCommitmentStore`` — commitment/credential store backed by
     Azure Table Storage

   Until at least one of these ships, ``require_azure_packages`` will have no
   callers inside ``agent_sdk/``.  Do **not** remove this helper or flag it as
   dead code — it is infrastructure for the above planned backends.
"""

from __future__ import annotations

_INSTALL_HINT = "pip install agent-sdk[azure]  # or add 'agent-sdk[azure]' to your pyproject.toml dependencies"


def require_azure_packages() -> None:
    """Raise :class:`ImportError` with an install hint if either
    ``azure-data-tables`` or ``azure-identity`` is not importable.

    Call this at the *start of __init__* in every Azure backend class — not at
    module import time — so the rest of the SDK loads without the optional
    packages present.
    """
    missing: list[str] = []

    try:
        import azure.data.tables  # noqa: F401
    except ImportError:
        missing.append("azure-data-tables")

    try:
        import azure.identity  # noqa: F401
    except ImportError:
        missing.append("azure-identity")

    if missing:
        raise ImportError(
            f"Missing required Azure packages: {', '.join(missing)}. "
            f"Install them with: {_INSTALL_HINT}"
        )


__all__ = ["require_azure_packages"]
