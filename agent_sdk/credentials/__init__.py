"""Credential store: encrypted SQLite, namespaced per source (DESIGN.md §6)."""

from .fields import CredentialField
from .store import CredentialStore, resolver_for_source

__all__ = ["CredentialField", "CredentialStore", "resolver_for_source"]
