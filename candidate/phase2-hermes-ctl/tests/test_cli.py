"""Unit tests for the hermesctl CLI (offline, temp store)."""

import json
import os
import tempfile

from hermes_ctl.cli import build_parser, main


def _env(tmp):
    p = os.path.join(tmp, "store.json")
    os.environ["HERMES_CTL_STORE"] = p
    return p


def test_memory_remember_search_forget():
    with tempfile.TemporaryDirectory() as tmp:
        store = _env(tmp)
        assert main(["memory", "remember", "note1", json.dumps({"k": "v"}), "--tag", "test"]) == 0
        out = os.popen(f"HERMES_CTL_STORE={store} python3 -m hermes_ctl.cli memory search --tag test").read()
        assert "note1" in out and "v" in out
        assert main(["memory", "forget", "note1"]) == 0
        out2 = os.popen(f"HERMES_CTL_STORE={store} python3 -m hermes_ctl.cli memory search --tag test").read()
        assert "note1" not in out2


def test_inbox_list_filters_by_channel():
    with tempfile.TemporaryDirectory() as tmp:
        store = _env(tmp)
        # seed an inbox fact via the store directly
        from hermes_ctl.memory.store import MemoryStore
        s = MemoryStore(persist_path=store)
        s.remember("inbox:sms:1", {"channel": "sms", "sender": "+1", "body": "hi"}, tags=("inbox", "sms"))
        s.remember("inbox:email:1", {"channel": "email", "sender": "a@b", "body": "yo"}, tags=("inbox", "email"))
        out = os.popen(f"HERMES_CTL_STORE={store} python3 -m hermes_ctl.cli inbox list --channel sms").read()
        assert "[sms]" in out and "hi" in out and "email" not in out


def test_tasks_add_and_list():
    with tempfile.TemporaryDirectory() as tmp:
        store = _env(tmp)
        assert main(["tasks", "add", "write roadmap update"]) == 0
        out = os.popen(f"HERMES_CTL_STORE={store} python3 -m hermes_ctl.cli tasks list").read()
        assert "write roadmap update" in out


def test_identity_set_pref_and_show():
    with tempfile.TemporaryDirectory() as tmp:
        store = _env(tmp)
        assert main(["identity", "set-pref", "theme", "synthwave"]) == 0
        out = os.popen(f"HERMES_CTL_STORE={store} python3 -m hermes_ctl.cli identity show").read()
        assert "synthwave" in out


def test_notes_add_and_list():
    with tempfile.TemporaryDirectory() as tmp:
        store = _env(tmp)
        assert main(["notes", "add", "shopping list", "--body", "milk, eggs"]) == 0
        out = os.popen(f"HERMES_CTL_STORE={store} python3 -m hermes_ctl.cli notes list").read()
        assert "shopping list" in out


def test_calendar_add_and_upcoming():
    with tempfile.TemporaryDirectory() as tmp:
        store = _env(tmp)
        assert main(["calendar", "add", "dentist", "--in-days", "2"]) == 0
        out = os.popen(f"HERMES_CTL_STORE={store} python3 -m hermes_ctl.cli calendar upcoming").read()
        assert "dentist" in out


def test_crm_add_and_find():
    with tempfile.TemporaryDirectory() as tmp:
        store = _env(tmp)
        assert main(["crm", "add", "Courtney", "--kind", "partner"]) == 0
        out = os.popen(f"HERMES_CTL_STORE={store} python3 -m hermes_ctl.cli crm find Courtney").read()
        assert "Courtney" in out and "partner" in out


def test_send_email_blocked_without_creds(monkeypatch, tmp_path):
    # no creds in env -> SecretError -> send blocked (rc 1)
    monkeypatch.delenv("GMAIL_SMTP_USER", raising=False)
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    rc = main(["send", "email", "--to", "x@y.com", "--body", "hi"])
    assert rc == 1


def test_send_telegram_routes_to_channel(monkeypatch, tmp_path):
    # stub TelegramChannel.send to avoid network; creds present
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    sent = {}

    class FakeCh:
        def send(self, message):
            sent["to"] = message.recipient
            sent["body"] = message.body
            message.id = "99"
            return "99"

    import hermes_ctl.cli as cli
    monkeypatch.setattr(cli, "TelegramChannel", lambda token=None: FakeCh())
    rc = main(["send", "telegram", "--to", "7620778176", "--body", "hello"])
    assert rc == 0
    assert sent == {"to": "7620778176", "body": "hello"}


def test_parser_requires_subcommand():
    import pytest
    with pytest.raises(SystemExit):
        build_parser().parse_args([])
