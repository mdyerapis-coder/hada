"""Unit tests for the EmailChannel (Phase 2), offline via monkeypatched SMTP/IMAP."""

import email
from email.message import EmailMessage

from hermes_ctl.communications.channels import Message
from hermes_ctl.communications.email import EmailChannel


class _FakeSMTP:
    instances: list = []

    def __init__(self, host, port, context=None):
        self.host = host
        self.port = port
        self.sent: list[EmailMessage] = []
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, user, pw):
        self.user = user
        self.pw = pw

    def send_message(self, msg):
        self.sent.append(msg)


class _FakeIMAP:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.logged_in = False

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, user, pw):
        self.logged_in = True
        self.user = user

    def select(self, box):
        return "OK", [b"1"]

    def search(self, *a):
        return "OK", [b"1"]

    def fetch(self, num, spec):
        m = EmailMessage()
        m["From"] = "sender@example.com"
        m["To"] = "dyer.mason1994@gmail.com"
        m["Subject"] = "Test"
        m.set_content("hello email body")
        return "OK", [(b"1", m.as_bytes())]


def test_email_send_uses_creds_and_sends(monkeypatch):
    monkeypatch.setattr("smtplib.SMTP_SSL", _FakeSMTP)
    ch = EmailChannel(user="dyer.mason1994@gmail.com", password="rppa bmzu itzd azpj")
    mid = ch.send(Message(channel="email", sender="a", recipient="b@x.com", subject="Hi", body="test"))
    assert mid
    smtp = _FakeSMTP.instances[-1]
    assert smtp.user == "dyer.mason1994@gmail.com"
    assert smtp.pw == "rppabmzuitzdazpj"  # spaces stripped
    assert smtp.sent[0]["To"] == "b@x.com"
    assert smtp.sent[0].get_content().strip() == "test"


def test_email_password_spaces_stripped_on_login(monkeypatch):
    monkeypatch.setattr("smtplib.SMTP_SSL", _FakeSMTP)
    ch = EmailChannel(user="u@gmail.com", password="aaaa bbbb cccc dddd")
    ch.send(Message(channel="email", sender="a", recipient="r@x.com", subject="s", body="b"))
    assert _FakeSMTP.instances[-1].pw == "aaaabbbbccccdddd"


def test_email_requires_creds():
    ch = EmailChannel()  # no creds, no env
    import os

    monkeypatch_delenv = os.environ.pop("GMAIL_SMTP_USER", None)
    monkeypatch_delenv2 = os.environ.pop("GMAIL_APP_PASSWORD", None)
    try:
        ch.send(Message(channel="email", sender="a", recipient="r@x.com", subject="s", body="b"))
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass
    if monkeypatch_delenv is not None:
        os.environ["GMAIL_SMTP_USER"] = monkeypatch_delenv
    if monkeypatch_delenv2 is not None:
        os.environ["GMAIL_APP_PASSWORD"] = monkeypatch_delenv2


def test_email_received_parses_messages(monkeypatch):
    monkeypatch.setattr("imaplib.IMAP4_SSL", _FakeIMAP)
    ch = EmailChannel(user="u@gmail.com", password="aaaa bbbb cccc dddd")
    msgs = ch.received(limit=5)
    assert len(msgs) == 1
    assert msgs[0].body.strip() == "hello email body"
    assert "sender@example.com" in msgs[0].sender
