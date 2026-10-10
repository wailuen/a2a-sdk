from agent_sdk.common.limits import client_ip

TRUSTED = ["10.0.0.1"]


def test_untrusted_peer_ignores_xff():
    assert client_ip("9.9.9.9", "6.6.6.6", TRUSTED) == "9.9.9.9"


def test_trusted_peer_spoofed_leftmost_is_ignored():
    assert client_ip("10.0.0.1", "6.6.6.6, 203.0.113.7", TRUSTED) == "203.0.113.7"


def test_all_hops_trusted_gives_leftmost():
    assert client_ip("10.0.0.1", "10.0.0.1, 10.0.0.1", TRUSTED) == "10.0.0.1"


def test_no_peer_unknown():
    assert client_ip(None, None, TRUSTED) == "unknown"


def test_unauth_limiter_key_groups_ipv6_slash64():
    from types import SimpleNamespace

    from agent_sdk.auth.middleware import _client_key

    def key(host):
        req = SimpleNamespace(client=SimpleNamespace(host=host), headers={})
        return _client_key(req, SimpleNamespace(trusted_proxies=[]))

    assert key("2001:db8:1:2::1") == key("2001:db8:1:2:ffff::9")
    assert key("2001:db8:1:2::1") != key("2001:db8:1:3::1")
