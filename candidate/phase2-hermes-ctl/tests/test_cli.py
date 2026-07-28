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


def test_parser_requires_subcommand():
    import pytest
    with pytest.raises(SystemExit):
        build_parser().parse_args([])
