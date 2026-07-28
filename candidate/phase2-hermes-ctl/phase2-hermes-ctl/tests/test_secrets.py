"""Unit tests for the governed secret + network seams (offline)."""

import subprocess

from hermes_ctl.secrets import (
    EnvSecretStore,
    DictSecretStore,
    BitwardenSecretStore,
    SecretError,
    NetworkPolicy,
    NetworkDenied,
    default_contact_policy,
    Endpoint,
)


def test_env_store_returns_and_raises():
    s = EnvSecretStore({"GMAIL_APP_PASSWORD": "xxxx xxxx xxxx xxxx"})
    assert s.get("GMAIL_APP_PASSWORD") == "xxxx xxxx xxxx xxxx"
    try:
        s.get("NOPE")
        assert False, "should have raised"
    except SecretError:
        pass


def test_dict_store_injection():
    s = DictSecretStore({"TELEGRAM_BOT_TOKEN": "123:abc"})
    assert s.get("TELEGRAM_BOT_TOKEN") == "123:abc"
    try:
        s.get("missing")
        assert False
    except SecretError:
        pass


def test_bitwarden_store_invokes_bw_get_password(monkeypatch):
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        captured["env_has_session"] = "BW_SESSION" in kw.get("env", {})
        class R:
            stdout = "secret-from-bw\n"
            returncode = 0
        return R()

    monkeypatch.setattr(subprocess, "run", fake_run)
    s = BitwardenSecretStore(resolver=lambda name: "item-id-123", session="sess")
    assert s.get("GMAIL_APP_PASSWORD") == "secret-from-bw"
    assert captured["cmd"][:3] == ["bw", "get", "password"]
    # session injected into the subprocess env (not global os.environ)
    assert captured["env_has_session"] is True


def test_bitwarden_store_raises_on_failure(monkeypatch):
    def fake_run(cmd, **kw):
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(subprocess, "run", fake_run)
    s = BitwardenSecretStore(resolver=lambda n: "id", session="s")
    try:
        s.get("X")
        assert False
    except SecretError:
        pass


def test_network_policy_default_deny():
    p = NetworkPolicy()
    assert not p.allows("https://evil.example.com:443")
    try:
        p.require("https://evil.example.com:443")
        assert False
    except NetworkDenied:
        pass


def test_network_policy_allows_registered():
    p = NetworkPolicy(["https://api.telegram.org:443", "imaps://imap.gmail.com:993"])
    assert p.allows("https://api.telegram.org:443")
    assert p.allows("imaps://imap.gmail.com:993")
    p.require("https://api.telegram.org:443")  # no raise
    # strict port match: wrong port is denied by default
    assert not p.allows("https://api.telegram.org:8443")
    # host-only broad allow via register_host
    p.register_host("api.telegram.org")
    assert p.allows("https://api.telegram.org:8443")


def test_endpoint_from_url_default_ports():
    assert Endpoint.from_url("https://api.telegram.org").port == 443
    assert Endpoint.from_url("http://host:8080").port == 8080


def test_default_contact_policy_known_hosts():
    p = default_contact_policy()
    assert p.allows("https://api.telegram.org:443")
    assert p.allows("imaps://imap.gmail.com:993")
    assert p.allows("smtps://smtp.gmail.com:465")
    assert not p.allows("https://example.com:443")
