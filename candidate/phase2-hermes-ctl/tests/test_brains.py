"""Tests for the llmfit brains.yaml loader (offline)."""

import os
import tempfile

from hermes_ctl.intelligence.brains import load_brains, _strip_endpoint, _apply_host_override


def _write(tmp: str, text: str) -> str:
    p = os.path.join(tmp, "brains.yaml")
    with open(p, "w") as fh:
        fh.write(text)
    return p


YAML = """
brains:
  fast:
    endpoint: http://127.0.0.1:8080/v1/chat/completions
    model: /models/model.gguf
  agent:
    endpoint: http://127.0.0.1:8081/v1/chat/completions
    model: /models/hermes-7b.gguf
  max:
    endpoint: http://127.0.0.1:8081/v1/chat/completions
    model: /models/hermes-7b.gguf
"""


def test_load_brains_parses_roles():
    with tempfile.TemporaryDirectory() as tmp:
        p = _write(tmp, YAML)
        brains = load_brains(p)
        assert {b.role for b in brains} == {"fast", "agent", "max"}
        fast = next(b for b in brains if b.role == "fast")
        # endpoint /chat/completions stripped -> base url for HttpRouter
        assert fast.url == "http://127.0.0.1:8080/v1"
        assert fast.model == "/models/model.gguf"


def test_load_brains_host_override():
    with tempfile.TemporaryDirectory() as tmp:
        p = _write(tmp, YAML)
        os.environ["HERMES_BRAIN_HOST"] = "100.109.135.0"
        try:
            brains = load_brains(p)
        finally:
            del os.environ["HERMES_BRAIN_HOST"]
        fast = next(b for b in brains if b.role == "fast")
        assert fast.url == "http://100.109.135.0:8080/v1"


def test_load_brains_missing_role_raises():
    with tempfile.TemporaryDirectory() as tmp:
        p = _write(tmp, "brains:\n  fast:\n    endpoint: http://127.0.0.1:8080/v1/chat/completions\n    model: x\n")
        try:
            load_brains(p)
            assert False, "should raise"
        except ValueError as e:
            assert "agent" in str(e)


def test_strip_endpoint_and_host_override_helpers():
    assert _strip_endpoint("http://h:8080/v1/chat/completions") == "http://h:8080/v1"
    assert _apply_host_override("http://127.0.0.1:8080/v1", "1.2.3.4") == "http://1.2.3.4:8080/v1"
    assert _apply_host_override("http://example.com:8080/v1", "1.2.3.4") == "http://example.com:8080/v1"
