import json

import pytest

from agent_config import AgentConfig
from feedback_client import (
    FeedbackSubmissionError,
    build_feedback_payload,
    submit_feedback,
)


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


def test_submit_feedback_requires_api_base_url():
    with pytest.raises(FeedbackSubmissionError) as excinfo:
        submit_feedback(
            category="bug",
            subject="No backend",
            message="This should fail cleanly.",
            app_version="v1.3.0",
            config=AgentConfig(),
        )
    assert "TRAVELPORT_AGENT_API_BASE_URL" in str(excinfo.value)
    assert "agent_config.json" in str(excinfo.value)
