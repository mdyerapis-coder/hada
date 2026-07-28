"""Unit tests for the unified contact daemon (offline)."""

from hermes_ctl.communications.contact_daemon import _store_inbox, _poll_loop
from hermes_ctl.communications.channels import Message
from hermes_ctl.memory.store import MemoryStore

import threading


def test_store_inbox_writes_tagged_fact():
    store = MemoryStore(persist_path=None)
    msg = Message(channel="email", sender="a@b.com", recipient="me@x.com",
                  subject="Hi", body="hello", id="m1")
    _store_inbox(store, msg, "m1")
    inbox = store.search(tag="inbox")
    assert len(inbox) == 1
    v = inbox[0].value
    assert v["channel"] == "email" and v["subject"] == "Hi" and v["body"] == "hello"


def test_poll_loop_stores_new_and_skips_seen():
    store = MemoryStore(persist_path=None)
    calls = {"n": 0}

    def fake_fetch():
        calls["n"] += 1
        # first call returns 2 msgs, later calls return the same (dedup by id)
        return [
            Message(channel="telegram", sender="1", recipient="2", body="a", id="x1"),
            Message(channel="telegram", sender="1", recipient="2", body="b", id="x2"),
        ]

    stop = threading.Event()
    t = threading.Thread(target=_poll_loop, args=(store, "telegram", fake_fetch, 0.01, stop))
    t.start()
    stop.wait(0.05)
    stop.set()
    t.join(timeout=2)
    # both messages stored once; repeat fetches are deduped by id
    inbox = store.search(tag="inbox")
    assert len(inbox) == 2
    assert calls["n"] >= 2  # loop ran multiple times
