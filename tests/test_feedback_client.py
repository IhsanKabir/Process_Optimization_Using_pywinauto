import json
import shutil
import urllib.error
from io import BytesIO
from pathlib import Path

import pytest

from agent_config import DEFAULT_API_BASE_URL, AgentConfig, load_agent_config
from feedback_client import (
    FeedbackQueuedForRetry,
    FeedbackSubmissionError,
    _scrub_context,
    build_feedback_payload,
    submit_feedback,
)


def _make_local_temp_dir(name: str) -> Path:
    path = Path.cwd() / name
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    return path


# ── Payload builder ────────────────────────────────────────────────────────────

def test_build_feedback_payload_includes_device_context(monkeypatch):
    monkeypatch.setattr("feedback_client.socket.gethostname", lambda: "DESKTOP-01")
    monkeypatch.setattr("feedback_client.platform.platform", lambda: "Windows-11")

    payload = build_feedback_payload(
        category="bug",
        subject="Crash on startup",
        message="The app failed before the first command.",
        app_version="v1.3.0",
        context={"mode": "fare"},
        config=AgentConfig(api_base_url="https://example.com/api/travelport-agent"),
    )

    assert payload["category"] == "bug"
    assert payload["subject"] == "Crash on startup"
    assert payload["device_name"] == "DESKTOP-01"
    assert payload["os_version"] == "Windows-11"
    assert payload["context"]["mode"] == "fare"


def test_build_payload_raises_on_missing_subject():
    with pytest.raises(FeedbackSubmissionError, match="subject"):
        build_feedback_payload(
            category="bug",
            subject="",
            message="Some message",
            app_version="v1.0.0",
            config=AgentConfig(api_base_url="https://example.com"),
        )


def test_build_payload_raises_on_missing_message():
    with pytest.raises(FeedbackSubmissionError, match="message"):
        build_feedback_payload(
            category="bug",
            subject="A subject",
            message="",
            app_version="v1.0.0",
            config=AgentConfig(api_base_url="https://example.com"),
        )


# ── PII scrubber ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("key", ["password", "PASSWORD", "token", "api_key", "secret", "auth", "cred", "pwd"])
def test_scrub_context_redacts_pii_keys(key):
    result = _scrub_context({key: "supersecret"})
    assert result[key] == "[REDACTED]"


@pytest.mark.parametrize("key", ["mode", "route_filter", "airline_filter"])
def test_scrub_context_passes_safe_keys(key):
    result = _scrub_context({key: "SG"})
    assert result[key] == "SG"


def test_scrub_context_redacts_windows_path_values():
    result = _scrub_context({"log_path": r"C:\Users\john\Desktop\report.xlsx"})
    assert result["log_path"] == "[REDACTED]"


def test_scrub_context_redacts_unix_path_values():
    result = _scrub_context({"log_path": "/home/john/report.xlsx"})
    assert result["log_path"] == "[REDACTED]"


def test_scrub_context_safe_values_pass_through():
    ctx = {"mode": "fare", "airline_filter": "BG", "route_filter": "DAC-MCT"}
    assert _scrub_context(ctx) == ctx


def test_scrub_context_redacts_nested_pii_key():
    """A PII key inside a nested dict must be redacted, not passed through."""
    result = _scrub_context({"session": {"token": "abc", "user": "bob"}})
    assert result["session"]["token"] == "[REDACTED]"
    assert result["session"]["user"] == "bob"


def test_scrub_context_redacts_nested_path_value():
    """A Windows path inside a nested dict must be redacted."""
    result = _scrub_context({"run_info": {"output_dir": r"C:\Users\alice\reports"}})
    assert result["run_info"]["output_dir"] == "[REDACTED]"


def test_scrub_context_redacts_pii_key_in_list():
    """PII key applies to all elements of a list value."""
    result = _scrub_context({"tokens": ["tok1", "tok2"]})
    # key "tokens" matches the PII pattern → entire value redacted
    assert result["tokens"] == "[REDACTED]"


# ── Default URL resolution ─────────────────────────────────────────────────────

def test_default_api_base_url_used_when_env_and_json_are_empty(monkeypatch):
    tmp_path = _make_local_temp_dir("tmp_test_feedback_default_url")
    monkeypatch.delenv("TRAVELPORT_AGENT_API_BASE_URL", raising=False)
    try:
        config = load_agent_config(config_path=tmp_path / "nonexistent.json")
        assert config.api_base_url == DEFAULT_API_BASE_URL
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_env_var_overrides_default(monkeypatch):
    tmp_path = _make_local_temp_dir("tmp_test_feedback_env_override")
    monkeypatch.setenv("TRAVELPORT_AGENT_API_BASE_URL", "https://custom.example.com/api")
    try:
        config = load_agent_config(config_path=tmp_path / "nonexistent.json")
        assert config.api_base_url == "https://custom.example.com/api"
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_json_overrides_default():
    tmp_path = _make_local_temp_dir("tmp_test_feedback_json_override")
    cfg_file = tmp_path / "agent_config.json"
    cfg_file.write_text(json.dumps({"api_base_url": "https://json.example.com"}), encoding="utf-8")
    try:
        config = load_agent_config(config_path=cfg_file)
        assert config.api_base_url == "https://json.example.com"
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


# ── Happy path ─────────────────────────────────────────────────────────────────

def test_submit_feedback_posts_json(monkeypatch):
    captured = {}

    class DummyResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"ok": true, "feedback_id": "fb_123"}'

    def fake_urlopen(request, timeout=0):
        captured["url"] = request.full_url
        captured["auth"] = request.get_header("Authorization")
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return DummyResponse()

    monkeypatch.setattr("feedback_client.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("feedback_client.socket.gethostname", lambda: "DESKTOP-02")
    monkeypatch.setattr("feedback_client.platform.platform", lambda: "Windows-10")

    result = submit_feedback(
        category="suggestion",
        subject="Add export filter",
        message="Please add a way to export only one airline.",
        app_version="v1.3.0",
        context={"airline_filter": "BG"},
        config=AgentConfig(
            api_base_url="https://example.com/api/travelport-agent",
            device_token="secret-token",
            device_id="device-1",
        ),
    )

    assert captured["url"].endswith("/feedback")
    assert captured["auth"] == "Bearer secret-token"
    assert captured["body"]["device_id"] == "device-1"
    assert result["feedback_id"] == "fb_123"


# ── Failure classification ─────────────────────────────────────────────────────

def _make_http_error(code: int, body: bytes = b"error detail") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="https://example.com/feedback",
        code=code,
        msg="error",
        hdrs=None,
        fp=BytesIO(body),
    )


def test_4xx_raises_feedback_submission_error_not_queued(monkeypatch):
    queued = []

    def _raise_400(*a, **kw):
        raise _make_http_error(400, b"bad request")

    monkeypatch.setattr("feedback_client.urllib.request.urlopen", _raise_400)
    monkeypatch.setattr("feedback_queue.enqueue_feedback", lambda p: queued.append(p))
    monkeypatch.setattr("feedback_client.socket.gethostname", lambda: "HOST")
    monkeypatch.setattr("feedback_client.platform.platform", lambda: "Windows")

    with pytest.raises(FeedbackSubmissionError, match="400"):
        submit_feedback(
            category="bug",
            subject="Test",
            message="Test message",
            app_version="v1.0.0",
            config=AgentConfig(api_base_url="https://example.com/api"),
        )

    assert queued == [], "4xx must NOT be queued"


def test_5xx_raises_queued_for_retry(monkeypatch):
    queued = []

    def _raise_503(*a, **kw):
        raise _make_http_error(503)

    monkeypatch.setattr("feedback_client.urllib.request.urlopen", _raise_503)
    monkeypatch.setattr("feedback_queue.enqueue_feedback", lambda p: queued.append(p))
    monkeypatch.setattr("feedback_client.socket.gethostname", lambda: "HOST")
    monkeypatch.setattr("feedback_client.platform.platform", lambda: "Windows")

    with pytest.raises(FeedbackQueuedForRetry):
        submit_feedback(
            category="bug",
            subject="Test",
            message="Test message",
            app_version="v1.0.0",
            config=AgentConfig(api_base_url="https://example.com/api"),
        )

    assert len(queued) == 1, "5xx must enqueue payload"


def test_url_error_raises_queued_for_retry(monkeypatch):
    queued = []

    def _raise_url_error(*a, **kw):
        raise urllib.error.URLError(reason="Network unreachable")

    monkeypatch.setattr("feedback_client.urllib.request.urlopen", _raise_url_error)
    monkeypatch.setattr("feedback_queue.enqueue_feedback", lambda p: queued.append(p))
    monkeypatch.setattr("feedback_client.socket.gethostname", lambda: "HOST")
    monkeypatch.setattr("feedback_client.platform.platform", lambda: "Windows")

    with pytest.raises(FeedbackQueuedForRetry, match="saved"):
        submit_feedback(
            category="bug",
            subject="Test",
            message="Test message",
            app_version="v1.0.0",
            config=AgentConfig(api_base_url="https://example.com/api"),
        )

    assert len(queued) == 1
