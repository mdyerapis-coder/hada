"""Unit tests for SmsChannel + webhook receiver (capcom6), offline."""

import base64
import json

from hermes_ctl.communications.channels import Message
from hermes_ctl.communications.sms import SmsChannel
from hermes_ctl.communications.webhook_receiver import handle_webhook, make_handler, payload_to_message, verify_signature
from hermes_ctl.memory.store import MemoryStore
from http.server import HTTPServer
from threading import Thread


class _Fake:
    def __init__(self):
        self.calls = []

    def get(self, path):
        self.calls.append(("GET", path))
        return [
            {"id": "m1", "sender": "+61400111222", "recipient": "+61400999888",
             "contentPreview": "inbound sms body", "createdAt": "2026-01-01T00:00:00Z"},
        ]

    def post(self, path, payload):
        self.calls.append(("POST", path, payload))
        return None


def test_sms_send_uses_basic_auth_and_message_path(monkeypatch):
    f = _Fake()
    captured = {}

    def fake_http(self, method, path, payload=None):
        captured["auth"] = self._auth_header()
        return f.post(path, payload)

    monkeypatch.setattr(SmsChannel, "_http", fake_http)
    ch = SmsChannel(base_url="http://phone:8080", username="u", password="p")
    mid = ch.send(Message(channel="sms", sender="self", recipient="+61400333444", body="hi"))
    assert mid == "sms:+61400333444"
    assert f.calls[0] == ("POST", "/message", {"textMessage": {"text": "hi"}, "phoneNumbers": ["+61400333444"]})
    # Basic auth header present, decodes to u:p
    head = captured["auth"]
    assert head.startswith("Basic ")
    assert base64.b64decode(head[6:]).decode() == "u:p"


def test_sms_received_parses_inbox(monkeypatch):
    f = _Fake()
    monkeypatch.setattr(SmsChannel, "_http", lambda self, m, p, pl=None: f.get(p))
    ch = SmsChannel(base_url="http://phone:8080", username="u", password="p")
    msgs = ch.received(limit=10)
    assert len(msgs) == 1
    assert msgs[0].sender == "+61400111222"
    assert msgs[0].body == "inbound sms body"
    assert msgs[0].channel == "sms"
    assert f.calls[0][1].startswith("/inbox")


def test_sms_requires_creds():
    ch = SmsChannel()
    import os
    u = os.environ.pop("SMS_GATEWAY_URL", None)
    nu = os.environ.pop("SMS_GATEWAY_USER", None)
    np = os.environ.pop("SMS_GATEWAY_PASS", None)
    try:
        ch.send(Message(channel="sms", sender="s", recipient="+61", body="x"))
        assert False
    except RuntimeError:
        pass
    finally:
        for k, v in (("SMS_GATEWAY_URL", u), ("SMS_GATEWAY_USER", nu), ("SMS_GATEWAY_PASS", np)):
            if v is not None:
                os.environ[k] = v


def test_webhook_payload_to_message():
    msg = payload_to_message({"message": "hello", "sender": "+61400", "recipient": "+61999", "messageId": "abc"})
    assert msg.body == "hello" and msg.sender == "+61400" and msg.id == "abc"


def test_signature_verify():
    secret = "key"
    body = b'{"a":1}'
    ts = "123"
    good = __import__("hmac").new(secret.encode(), body + ts.encode(), __import__("hashlib").sha256).hexdigest()
    assert verify_signature(secret, body, ts, good)
    assert not verify_signature(secret, body, ts, "deadbeef")


def test_webhook_receiver_stores_inbox():
    store = MemoryStore(persist_path=None)
    raw = json.dumps({"event": "sms:received", "payload": {"message": "ping", "sender": "+61400", "recipient": "+61999", "messageId": "x1"}}).encode()
    code, obj = handle_webhook(store, raw, {}, secret_key="")
    assert code == 200 and obj == {"ok": True}
    inbox = store.search(tag="inbox")
    assert len(inbox) == 1
    assert inbox[0].value["body"] == "ping"


def test_webhook_rejects_bad_signature():
    store = MemoryStore(persist_path=None)
    raw = json.dumps({"event": "sms:received", "payload": {"message": "x", "messageId": "y"}}).encode()
    code, obj = handle_webhook(store, raw, {"X-Signature": "sha256=bad"}, secret_key="key")
    assert code == 401
    assert store.search(tag="inbox") == []


def test_forwarder_payload_stored():
    store = MemoryStore(persist_path=None)
    raw = json.dumps({"from": "+61400111222", "text": "Your code is 123456",
                      "sentStamp": 1700000000000, "receivedStamp": 1700000001000, "sim": "0"}).encode()
    code, obj = handle_webhook(store, raw, {}, secret_key="", source="forwarder")
    assert code == 200 and obj.get("ok") is True
    inbox = store.search(tag="inbox")
    assert len(inbox) == 1
    v = inbox[0].value
    assert v["channel"] == "sms" and v["sender"] == "+61400111222"
    assert v["body"] == "Your code is 123456"


def test_auto_detect_forwarder():
    store = MemoryStore(persist_path=None)
    raw = json.dumps({"from": "+61", "text": "hi"}).encode()
    code, _ = handle_webhook(store, raw, {}, secret_key="", source="auto")
    assert code == 200
    assert store.search(tag="inbox")[0].value["body"] == "hi"


def test_auto_detect_unrecognized():
    store = MemoryStore(persist_path=None)
    code, obj = handle_webhook(store, b"{}", {}, secret_key="", source="auto")
    assert code == 400 and "unrecognized" in obj.get("error", "")
