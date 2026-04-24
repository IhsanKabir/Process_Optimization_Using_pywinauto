"""
Tests for feedback_client token precedence (Item 2.6):
  explicit user_session_token > keyring > TRAVELPORT_USER_TOKEN env var > device_token
"""

import json

import pytest

from agent_config import AgentConfig
from feedback_client import submit_feedback


class _DummyResponse:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return b'{"ok": true}'


@pytest.fixture(autouse=True)
def _no_real_keyring(monkeypatch):
    """Prevent tests from touching the real keyring."""
    import types

    fake = types.ModuleType("keyring")
    fake.get_password = lambda *a: None
    fake.set_password = lambda *a: None
    fake.errors = types.SimpleNamespace(PasswordDeleteError=Exception)

    import sys
    sys.modules["keyring"] = fake
    yield
    sys.modules.pop("keyring", None)


@pytest.fixture(autouse=True)
def _no_queue(monkeypatch):
    monkeypatch.setattr("feedback_queue.enqueue_feedback", lambda p: None)


def _capture_headers(monkeypatch) -> dict:
    captured = {}

    def fake_urlopen(request, timeout=0):
        captured["x_user_session"] = request.get_header("X-user-session")
        captured["authorization"] = request.get_header("Authorization")
        return _DummyResponse()

    monkeypatch.setattr("feedback_client.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("feedback_client.socket.gethostname", lambda: "HOST")
    monkeypatch.setattr("feedback_client.platform.platform", lambda: "Windows")
    return captured


_BASE_CONFIG = AgentConfig(
    api_base_url="https://example.com/api",
    device_token="device-tok",
    device_id="dev-1",
)

_SUBMIT_KWARGS = dict(
    category="bug",
    subject="Test",
    message="Test message",
    app_version="v1.0.0",
    config=_BASE_CONFIG,
)


def test_explicit_user_session_token_used_as_x_user_session(monkeypatch):
    captured = _capture_headers(monkeypatch)
    submit_feedback(**_SUBMIT_KWARGS, user_session_token="user-session-xyz")
    assert captured["x_user_session"] == "user-session-xyz"
    assert captured["authorization"] is None


def test_keyring_token_preferred_over_device_token(monkeypatch):
    captured = _capture_headers(monkeypatch)

    import types, sys
    fake_keyring = types.ModuleType("keyring")
    fake_keyring.get_password = lambda *a: "keyring-session-tok"
    fake_keyring.errors = types.SimpleNamespace(PasswordDeleteError=Exception)
    sys.modules["keyring"] = fake_keyring

    submit_feedback(**_SUBMIT_KWARGS)
    assert captured["x_user_session"] == "keyring-session-tok"
    assert captured["authorization"] is None


def test_env_var_user_token_used_when_keyring_empty(monkeypatch):
    captured = _capture_headers(monkeypatch)
    monkeypatch.setenv("TRAVELPORT_USER_TOKEN", "env-session-tok")
    submit_feedback(**_SUBMIT_KWARGS)
    assert captured["x_user_session"] == "env-session-tok"
    assert captured["authorization"] is None


def test_device_token_fallback_when_no_user_session(monkeypatch):
    captured = _capture_headers(monkeypatch)
    monkeypatch.delenv("TRAVELPORT_USER_TOKEN", raising=False)
    submit_feedback(**_SUBMIT_KWARGS)
    assert captured["x_user_session"] is None
    assert captured["authorization"] == "Bearer device-tok"


def test_explicit_token_overrides_env_and_keyring(monkeypatch):
    captured = _capture_headers(monkeypatch)
    monkeypatch.setenv("TRAVELPORT_USER_TOKEN", "env-session-tok")

    import types, sys
    fake_keyring = types.ModuleType("keyring")
    fake_keyring.get_password = lambda *a: "keyring-session-tok"
    fake_keyring.errors = types.SimpleNamespace(PasswordDeleteError=Exception)
    sys.modules["keyring"] = fake_keyring

    submit_feedback(**_SUBMIT_KWARGS, user_session_token="explicit-tok")
    assert captured["x_user_session"] == "explicit-tok"


def test_device_id_always_in_payload(monkeypatch):
    captured_body = {}

    def fake_urlopen(request, timeout=0):
        captured_body["data"] = json.loads(request.data.decode("utf-8"))
        return _DummyResponse()

    monkeypatch.setattr("feedback_client.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("feedback_client.socket.gethostname", lambda: "HOST")
    monkeypatch.setattr("feedback_client.platform.platform", lambda: "Windows")
    monkeypatch.delenv("TRAVELPORT_USER_TOKEN", raising=False)

    submit_feedback(**_SUBMIT_KWARGS, user_session_token="user-tok")
    assert captured_body["data"]["device_id"] == "dev-1"
