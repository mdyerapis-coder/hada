"""Unit tests for the Hermes CTL Intelligence layer (Phase 2, Cycle 11)."""

from hermes_ctl.intelligence.router import (
    Brain,
    LocalRouter,
    default_brains,
)


def test_default_brains_three_roles():
    brains = default_brains()
    assert {b.role for b in brains} == {"fast", "agent", "max"}
    # auth_header names the header, never carries a secret value
    assert all(b.auth_header for b in brains)


def test_local_router_selects_by_role():
    r = LocalRouter(default_brains())
    fast = r.select("fast")
    agent = r.select("agent")
    assert fast.role == "fast" and fast.model == "qwen3b"
    assert agent.role == "agent" and "hermes-7b" in agent.model


def test_local_router_missing_role_raises():
    r = LocalRouter([Brain(name="fast", role="fast", url="x", model="m")])
    try:
        r.select("max")
        assert False, "expected KeyError"
    except KeyError:
        pass


def test_local_router_register_override():
    r = LocalRouter([])
    r.register(Brain(name="max", role="max", url="http://x/v1", model="big"))
    assert r.select("max").model == "big"
