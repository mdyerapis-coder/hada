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


def test_brains_command_lists_roles(monkeypatch, tmp_path):
    p = tmp_path / "brains.yaml"
    p.write_text(
        "brains:\n"
        "  fast:\n    endpoint: http://127.0.0.1:8080/v1/chat/completions\n    model: m\n"
        "  agent:\n    endpoint: http://127.0.0.1:8081/v1/chat/completions\n    model: m\n"
        "  max:\n    endpoint: http://127.0.0.1:8081/v1/chat/completions\n    model: m\n"
    )
    monkeypatch.setenv("HERMES_BRAINS_PATH", str(p))
    rc = main(["brains"])
    assert rc == 0


def test_briefing_validate_ok(monkeypatch, tmp_path):
    from hermes_ctl.intelligence.briefing import generate_briefing, Prescription, deliver_briefing
    b = generate_briefing(
        [Prescription(id="mem-a", cat="MEMORY", tone="pink", headline="h",
                      prescription="p", evidence=["a", "b", "c"], command="x")],
        date="2026-07-28", model="m")
    f = tmp_path / "dream.json"
    deliver_briefing(b, dreams_dir=str(tmp_path))
    import json, glob
    f = glob.glob(str(tmp_path / "dream-*.json"))[0]
    assert main(["briefing", "validate", f]) == 0


def test_briefing_validate_rejects_bad(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"date": "2026-07-28", "model": "m", "generatedAt": "x", "prescriptions": []}))
    assert main(["briefing", "validate", str(bad)]) == 1


def test_briefing_run_executes(monkeypatch, tmp_path):
    import hermes_ctl.cli as cli
    from hermes_ctl.intelligence.briefing import run_briefing

    class _CliFakeRouter:
        def __init__(self, replies):
            self._replies = list(replies)
        def complete(self, role, prompt, *, max_tokens=400):
            return self._replies.pop(0)

    monkeypatch.setattr(cli, "load_brains", lambda: object())
    monkeypatch.setattr("hermes_ctl.intelligence.http_router.HttpRouter", lambda b: _CliFakeRouter([
        '{"headline":"h1","prescription":"p1","evidence":["a","b","c"],"command":"x"}',
        '{"headline":"h2","prescription":"p2","evidence":["d","e","f"],"command":"y"}',
        '{"headline":"h3","prescription":"p3","evidence":["g","h","i"],"command":"z"}',
        '{"headline":"h4","prescription":"p4","evidence":["j","k","l"],"command":"w"}',
    ]))
    monkeypatch.setenv("HERMES_CTL_STORE", str(tmp_path / "store.json"))
    monkeypatch.setenv("HERMES_DREAMS_DIR", str(tmp_path / "dreams"))
    assert main(["briefing", "run"]) == 0


def test_parser_requires_subcommand():
    import pytest
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


# =======================================================================
# memory curate / consolidate CLI
# =======================================================================


def test_memory_curate_empty(tmp_path):
    """memory curate on empty store returns no suggestions."""
    store = _env(tmp_path)
    out = os.popen(f"HERMES_CTL_STORE={store} python3 -m hermes_ctl.cli memory curate").read()
    assert "0 facts" in out


def test_memory_curate_with_data(tmp_path):
    """memory curate ranks facts by importance."""
    store = _env(tmp_path)
    from hermes_ctl.memory.store import MemoryStore
    s = MemoryStore(persist_path=store)
    s.remember("task:buy-milk", {"body": "buy milk"}, tags=("inbox",))
    s.remember("note:old-thought", {"body": "old thought from ages ago"}, tags=("stale",), ttl=None)
    out = os.popen(f"HERMES_CTL_STORE={store} python3 -m hermes_ctl.cli memory curate").read()
    assert "Curation suggestions" in out
    assert "buy-milk" in out or "old-thought" in out


def test_memory_consolidate_empty(tmp_path):
    """memory consolidate on empty store returns no groups."""
    store = _env(tmp_path)
    out = os.popen(f"HERMES_CTL_STORE={store} python3 -m hermes_ctl.cli memory consolidate").read()
    assert "0 group" in out


def test_memory_consolidate_with_similar(tmp_path):
    """memory consolidate detects similar facts."""
    store = _env(tmp_path)
    from hermes_ctl.memory.store import MemoryStore
    s = MemoryStore(persist_path=store)
    s.remember("msg:1", {"body": "Can you pick up milk and bread"}, tags=("inbox", "sms"))
    s.remember("msg:2", {"body": "Please grab milk and bread from shop"}, tags=("inbox", "sms"))
    out = os.popen(
        f"HERMES_CTL_STORE={store} python3 -m hermes_ctl.cli memory consolidate --threshold 0.4"
    ).read()
    assert "Consolidation suggestions" in out
    assert "msg:" in out

