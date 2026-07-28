"""Unit tests for the Hermes CTL Identity layer (Phase 2, Cycle 7)."""

from hermes_ctl.identity.profile import Identity, IdentityError
from hermes_ctl.memory.store import MemoryStore


def test_profile_merge_and_read():
    idn = Identity(MemoryStore())
    idn.set_profile(name="Mason Dyer", role="owner", tz="Australia/Melbourne")
    idn.set_profile(locale="en_AU")  # merges, not replaces
    p = idn.get_profile()
    assert p["name"] == "Mason Dyer"
    assert p["role"] == "owner"
    assert p["tz"] == "Australia/Melbourne"
    assert p["locale"] == "en_AU"


def test_preferences_set_get_default():
    idn = Identity(MemoryStore())
    idn.set_preference("theme", "synthwave")
    assert idn.get_preference("theme") == "synthwave"
    assert idn.get_preference("missing", "fallback") == "fallback"
    assert idn.all_preferences() == {"theme": "synthwave"}


def test_preference_key_validation():
    idn = Identity(MemoryStore())
    try:
        idn.set_preference("", "x")
        assert False, "expected IdentityError"
    except IdentityError:
        pass


def test_context_is_volatile_working_memory():
    store = MemoryStore()
    idn = Identity(store)
    idn.set_context(session_id="abc", turn=3)
    assert idn.get_context("turn") == 3
    assert idn.get_context("session_id") == "abc"
    idn.clear_context()
    assert idn.get_context("turn", None) is None


def test_identity_persists_with_store():
    store = MemoryStore(persist_path=__import__("tempfile").mkdtemp() + "/mem.json")
    idn = Identity(store)
    idn.set_profile(name="Mason")
    idn.set_preference("theme", "synthwave")
    # fresh instances over the same backing store
    idn2 = Identity(store)
    assert idn2.get_profile()["name"] == "Mason"
    assert idn2.get_preference("theme") == "synthwave"
