import shutil
from pathlib import Path

from agent_config import DEFAULT_AGENT_CONFIG_PATH, load_agent_config


def test_default_agent_config_path_points_to_repo_runtime_dir():
    assert DEFAULT_AGENT_CONFIG_PATH.name == "agent_config.json"


def _make_local_temp_dir(name: str) -> Path:
    path = Path.cwd() / name
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    return path


def test_load_agent_config_from_json_file():
    tmp_path = _make_local_temp_dir("tmp_test_agent_config_json")
    config_path = tmp_path / "agent_config.json"
    config_path.write_text(
        """
{
  "api_base_url": "https://example.com/api/travelport-agent",
  "device_id": "device-123",
  "device_token": "token-abc",
  "poll_interval_seconds": 20,
  "heartbeat_interval_seconds": 25,
  "upload_reports": true,
  "upload_logs": false,
  "keep_local_reports": true,
  "keep_local_logs": false,
  "stop_check_interval_seconds": 7
}
""".strip(),
        encoding="utf-8",
    )

    try:
        config = load_agent_config(config_path)

        assert config.api_base_url == "https://example.com/api/travelport-agent"
        assert config.device_id == "device-123"
        assert config.device_token == "token-abc"
        assert config.poll_interval_seconds == 20
        assert config.heartbeat_interval_seconds == 25
        assert config.upload_reports is True
        assert config.upload_logs is False
        assert config.keep_local_reports is True
        assert config.keep_local_logs is False
        assert config.stop_check_interval_seconds == 7
        assert config.is_configured is True
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_load_agent_config_prefers_environment(monkeypatch):
    tmp_path = _make_local_temp_dir("tmp_test_agent_config_env")
    config_path = tmp_path / "agent_config.json"
    config_path.write_text(
        '{"api_base_url":"https://json.example","device_token":"json-token"}',
        encoding="utf-8",
    )

    monkeypatch.setenv(
        "TRAVELPORT_AGENT_API_BASE_URL",
        "https://env.example/api/travelport-agent",
    )
    monkeypatch.setenv("TRAVELPORT_AGENT_DEVICE_TOKEN", "env-token")
    monkeypatch.setenv("TRAVELPORT_AGENT_UPLOAD_LOGS", "false")

    try:
        config = load_agent_config(config_path)

        assert config.api_base_url == "https://env.example/api/travelport-agent"
        assert config.device_token == "env-token"
        assert config.upload_logs is False
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)
