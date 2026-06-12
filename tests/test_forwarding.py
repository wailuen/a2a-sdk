"""Per-call credential forwarding: fail-closed parse + layered resolution.

Security-critical (DESIGN §6.4): the X-Agent-Credentials envelope must parse
strictly and fail closed (any defect → {}), forwarded creds must take priority
over the store, an absent header must be exactly the stored behavior, and a
reserved (dunder) namespace must never be honored.
"""

from __future__ import annotations

import asyncio
import base64
import json

import pytest

from agent_sdk.credentials import forwarding
from agent_sdk.credentials.store import CredentialStore, resolver_for_source


def env(obj) -> str:
    return base64.b64encode(json.dumps(obj).encode()).decode()


class DictStore(CredentialStore):
    def __init__(self, data=None):
        self.data = dict(data or {})

    def get(self, namespace, field):
        return self.data.get(f"{namespace}/{field}")

    def set(self, namespace, field, value):
        self.data[f"{namespace}/{field}"] = value

    def delete(self, namespace, field):
        self.data.pop(f"{namespace}/{field}", None)

    def list_fields(self, namespace):
        return [k.split("/", 1)[1] for k in self.data if k.startswith(namespace + "/")]

    def close(self):
        pass


@pytest.fixture(autouse=True)
def _clean_context():
    """Each test starts with no forwarded creds and restores after."""
    token = forwarding.bind({})
    yield
    forwarding.unbind(token)


# ── parse_header: the happy path ──

def test_parse_namespaced_envelope():
    creds = forwarding.parse_header(env({"alphageo": {"api_key": "secret-123"}}))
    assert creds == {"alphageo": {"api_key": "secret-123"}}


def test_absent_header_is_empty():
    assert forwarding.parse_header(None) == {}
    assert forwarding.parse_header("") == {}


# ── parse_header: fail closed on every defect ──

@pytest.mark.parametrize(
    "raw",
    [
        "not%%%base64",                       # not base64
        base64.b64encode(b"not json").decode(),  # not json
        env([1, 2, 3]),                       # not an object
        env({"alphageo": "flat-string"}),     # fields not a dict
        env({"alphageo": {"api_key": 123}}),  # value not a string
        env({"Bad-Name": {"api_key": "x"}}),  # source fails name regex
        env({"alphageo": {"API_KEY": "x"}}),  # field fails name regex
        env({"__bedrock__": {"k": "x"}}),     # reserved dunder namespace
        env({"alphageo": {"api_key": "x" * 4097}}),       # value too long
        env({f"s{i}": {"k": "x"} for i in range(17)}),    # too many sources
        env({"alphageo": {f"f{i}": "x" for i in range(17)}}),  # too many fields
    ],
)
def test_fail_closed(raw):
    assert forwarding.parse_header(raw) == {}


def test_oversized_envelope_rejected():
    big = base64.b64encode(b"{" + b'"x":1,' * 5000 + b"}").decode()
    assert forwarding.parse_header(big) == {}


def test_jwt_field_gets_larger_cap():
    # jwt_private_key may be up to 8192; a 4097-char plain field would be cut,
    # but a 5000-char jwt_private_key is accepted.
    ok = forwarding.parse_header(env({"src": {"jwt_private_key": "x" * 5000}}))
    assert ok == {"src": {"jwt_private_key": "x" * 5000}}
    too_big = forwarding.parse_header(env({"src": {"jwt_private_key": "x" * 8193}}))
    assert too_big == {}


# ── layered resolution: forwarded first, store fallback ──

def test_forwarded_takes_priority_over_store():
    store = DictStore({"alphageo/api_key": "STORED"})
    resolve = resolver_for_source(store, "alphageo")
    assert resolve("alphageo", "api_key") == "STORED"  # no header → store

    forwarding.bind({"alphageo": {"api_key": "FORWARDED"}})
    assert resolve("alphageo", "api_key") == "FORWARDED"  # header wins


def test_absent_forward_falls_back_to_store():
    store = DictStore({"alphageo/api_key": "STORED"})
    resolve = resolver_for_source(store, "alphageo")
    forwarding.bind({"other_source": {"api_key": "x"}})  # different namespace
    assert resolve("alphageo", "api_key") == "STORED"


def test_missing_everywhere_is_none():
    resolve = resolver_for_source(DictStore(), "alphageo")
    assert resolve("alphageo", "api_key") is None


def test_reserved_namespace_has_no_resolver():
    with pytest.raises(ValueError):
        resolver_for_source(DictStore(), "__bedrock__")


# ── request scoping: unbind restores the prior context ──

def test_unbind_restores():
    store = DictStore({"alphageo/api_key": "STORED"})
    resolve = resolver_for_source(store, "alphageo")
    token = forwarding.bind({"alphageo": {"api_key": "REQ"}})
    assert resolve("alphageo", "api_key") == "REQ"
    forwarding.unbind(token)
    assert resolve("alphageo", "api_key") == "STORED"


async def test_create_task_snapshot_isolation():
    """The A2A set-site binds in the request task, then create_task spawns the
    worker (which snapshots the context). Concurrent 'requests' must each see
    ONLY their own forwarded key — proving the contextvar is request-scoped,
    never a shared mutable global."""
    resolve = resolver_for_source(DictStore(), "probe")

    async def worker(_key):
        await asyncio.sleep(0.01)  # widen the interleave window
        return resolve("probe", "api_key")

    async def request(key):
        forwarding.bind({"probe": {"api_key": key}})  # like _start_worker
        return await asyncio.create_task(worker(key))  # snapshots context

    keys = [f"KEY-{i}" for i in range(25)]
    results = await asyncio.gather(*[asyncio.create_task(request(k)) for k in keys])
    assert results == keys  # zero cross-contamination
