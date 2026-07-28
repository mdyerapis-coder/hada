"""Unit tests for SmsChannel (handset gateway), offline via monkeypatched HTTP."""

from hermes_ctl.communications.channels import Message
from hermes_ctl.communications.sms import SmsChannel


class _Fake:
    def __init__(self):
        self.gets = []
        self.posts = []

    def get(self, path):
        self.gets.append(path)
        # emulate a handset gateway message list
        return [
            {"id": "1", "sender": "+61400111222", "text": "inbound sms body", "received": "t1"},
            {"id": "2", "sender": "+61400333444", "text": "second msg", "received": "t2"},
        ]

    def post(self, path, payload):
        self.posts.append((path, payload))
        return {"ok": True, "id": "99"}


def test_sms_received_parses(monkeypatch):
    f = _Fake()
    monkeypatch.setattr(SmsChannel, "_http_get", lambda self, p: f.get(p))
    ch = SmsChannel(base_url="http://phone:8080", token="x")
    msgs = ch.received(limit=10)
    assert len(msgs) == 2
    assert msgs[0].sender == "+61400111222"
    assert msgs[0].body == "inbound sms body"
    assert msgs[0].channel == "sms"


def test_sms_send_posts_to_gateway(monkeypatch):
    f = _Fake()
    monkeypatch.setattr(SmsChannel, "_http_post", lambda self, p, pl: f.post(p, pl))
    ch = SmsChannel(base_url="http://phone:8080", token="x")
    mid = ch.send(Message(channel="sms", sender="self", recipient="+61400999888", body="hi"))
    assert mid == "sms:+61400999888"
    assert f.posts[0][0] == "/send"
    assert f.posts[0][1] == {"to": "+61400999888", "text": "hi"}


def test_sms_requires_url():
    ch = SmsChannel()  # no url, no env
    import os

    u = os.environ.pop("SMS_GATEWAY_URL", None)
    t = os.environ.pop("SMS_GATEWAY_TOKEN", None)
    try:
        ch.received()
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass
    finally:
        if u is not None:
            os.environ["SMS_GATEWAY_URL"] = u
        if t is not None:
            os.environ["SMS_GATEWAY_TOKEN"] = t


def test_sms_token_never_in_repr():
    ch = SmsChannel(base_url="http://phone:8080", token="SECRET")
    assert "SECRET" not in repr(ch)
