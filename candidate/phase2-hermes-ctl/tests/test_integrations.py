"""Unit tests for gated Phase 2 integrations (Telegram + HttpRouter), offline."""

import json

from hermes_ctl.communications.channels import Message
from hermes_ctl.communications.telegram import TelegramChannel
from hermes_ctl.intelligence.http_router import HttpRouter
from hermes_ctl.intelligence.router import Brain, default_brains


class _FakeResp:
    def __init__(self, payload: dict):
        self._p = payload

    def read(self):
        return json.dumps(self._p).encode("utf-8")


def test_telegram_send_uses_token_and_posts(monkeypatch):
    sent = {}

    def fake_post(self, method, payload):
        sent["method"] = method
        sent["payload"] = payload
        return {"ok": True, "result": {"message_id": 42}}

    monkeypatch.setattr(TelegramChannel, "_post", fake_post)
    ch = TelegramChannel(token="SECRET-SHOULD-NEVER-BE-LOGGED")
    mid = ch.send(Message(channel="telegram", sender="bot", recipient="123", body="hi"))
    assert mid == "42"
    assert sent["method"] == "sendMessage"
    assert sent["payload"]["chat_id"] == "123"
    assert sent["payload"]["text"] == "hi"


def test_telegram_requires_token(monkeypatch):
    import os

    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    ch = TelegramChannel()  # no token
    try:
        ch.send(Message(channel="telegram", sender="b", recipient="1", body="x"))
        assert False, "expected RuntimeError (no token)"
    except RuntimeError:
        pass


def test_telegram_token_never_serialized():
    # The token must not appear in the channel's repr/state that could be logged
    ch = TelegramChannel(token="TOPSECRET")
    assert "TOPSECRET" not in repr(ch)


def test_http_router_selects_and_completes(monkeypatch):
    captured = {}

    def fake_post(self, brain, payload):
        captured["url"] = brain.url
        captured["model"] = brain.model
        captured["headers"] = self._auth_headers(brain)
        return {"choices": [{"message": {"content": "hello from model"}}]}

    monkeypatch.setattr(HttpRouter, "_post", fake_post)
    # token resolver returns a value for the fast header only
    router = HttpRouter(default_brains(), token_resolver=lambda h: "KEY" if h == "X-Hermes-Fast-Key" else None)
    out = router.complete("fast", "ping")
    assert out == "hello from model"
    assert captured["model"] == "qwen3b"
    # auth header injected only when resolver supplies it
    assert captured["headers"].get("X-Hermes-Fast-Key") == "KEY"


def test_http_router_injects_no_secret_when_unresolved(monkeypatch):
    captured = {}

    def fake_post(self, brain, payload):
        captured["headers"] = self._auth_headers(brain)
        return {"choices": [{"message": {"content": "x"}}]}

    monkeypatch.setattr(HttpRouter, "_post", fake_post)
    router = HttpRouter(default_brains(), token_resolver=lambda h: None)
    router.complete("agent", "hi")
    # agent header name present but no value (key not leaked)
    assert "X-Hermes-Agent-Key" not in captured["headers"]
