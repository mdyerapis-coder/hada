"""Unit tests for the Hermes CTL Communications layer (Phase 2, Cycle 8)."""

from hermes_ctl.communications.channels import (
    Directory,
    LocalChannel,
    Message,
)
from hermes_ctl.memory.store import MemoryStore


def test_message_content_hash_stable():
    m1 = Message(channel="local", sender="a", recipient="b", body="hi")
    m2 = Message(channel="local", sender="a", recipient="b", body="hi")
    assert m1.content_hash() == m2.content_hash()
    assert m1.with_id().id == m2.with_id().id


def test_local_channel_send_delivers_to_inbox():
    ch = LocalChannel()
    mid = ch.send(Message(channel="local", sender="a", recipient="b", body="hello"))
    assert mid
    assert len(ch.outbox()) == 1
    received = ch.received()
    assert len(received) == 1
    assert received[0].body == "hello"
    assert received[0].recipient == "b"


def test_directory_add_get_contact():
    d = Directory(MemoryStore())
    d.add_contact("courtney", name="Courtney", relation="partner")
    contact = d.get_contact("courtney")
    assert contact is not None
    assert contact["name"] == "Courtney"
    assert "courtney" in d.all_contacts()
    assert d.get_contact("ghost") is None


def test_directory_persists():
    store = MemoryStore(persist_path=__import__("tempfile").mkdtemp() + "/mem.json")
    d1 = Directory(store)
    d1.add_contact("janni", name="Janni")
    d2 = Directory(store)
    c = d2.get_contact("janni")
    assert c is not None and c["name"] == "Janni"


def test_directory_requires_memory_store():
    try:
        Directory(object())  # type: ignore[arg-type]
        assert False, "expected TypeError"
    except TypeError:
        pass
