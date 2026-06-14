"""Credential store: encrypted SQLite, namespaced per source (DESIGN.md §6)."""

from .fields import CredentialField
from .store import CredentialStore, resolver_for_source

try:
    from .azure_table import AzureTableCredentialStore
except ImportError:
    pass

__all__ = ["CredentialField", "CredentialStore", "resolver_for_source"]
