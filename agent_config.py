"""
agent_config.py - Local agent configuration loader.

Keeps website/API integration settings separate from the core fare parsing
config so desktop deployments can be paired to a user account without
changing report-generation logic.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path


def _runtime_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


DEFAULT_AGENT_CONFIG_PATH = _runtime_dir() / "agent_config.json"

DEFAULT_API_BASE_URL = (
    "https://aero-pulse-api-591603094460.asia-south1.run.app/travelport-agent"
)

# Root of the live API — used for user-auth endpoints (/api/v1/user-auth/*)
AUTH_API_ROOT = "https://aero-pulse-api-591603094460.asia-south1.run.app"

# Google OAuth 2.0 client ID for the desktop "Sign in with Google" flow.
# Precedence: GOOGLE_OAUTH_CLIENT_ID env var → agent_config.json key → "".
def _load_google_client_id() -> str:
    if os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip():
        return os.environ["GOOGLE_OAUTH_CLIENT_ID"].strip()
    try:
        with open(DEFAULT_AGENT_CONFIG_PATH, "r", encoding="utf-8-sig") as _f:
            return str(json.load(_f).get("google_oauth_client_id", "")).strip()
    except Exception:
        return ""

GOOGLE_OAUTH_CLIENT_ID: str = _load_google_client_id()


@dataclass(frozen=True)
class AgentConfig:
    api_base_url: str = ""
    device_id: str = ""
    device_token: str = ""
    poll_interval_seconds: int = 15
    heartbeat_interval_seconds: int = 20
    upload_reports: bool = True
    upload_logs: bool = True
    keep_local_reports: bool = True
    keep_local_logs: bool = True
    stop_check_interval_seconds: int = 5

    @property
    def is_configured(self) -> bool:
        return bool(self.api_base_url and self.device_token)


def load_agent_config(config_path: str | os.PathLike | None = None) -> AgentConfig:
    """Load agent settings from env vars with optional JSON overrides."""
    path = Path(config_path) if config_path else DEFAULT_AGENT_CONFIG_PATH
    payload = {}

    if path.exists():
        with open(path, "r", encoding="utf-8-sig") as f:
            payload = json.load(f)

    api_base_url = (
        os.environ.get("TRAVELPORT_AGENT_API_BASE_URL")
        or payload.get("api_base_url", "")
        or DEFAULT_API_BASE_URL
    )
    device_id = os.environ.get("TRAVELPORT_AGENT_DEVICE_ID") or payload.get(
        "device_id", ""
    )
    device_token = os.environ.get("TRAVELPORT_AGENT_DEVICE_TOKEN") or payload.get(
        "device_token", ""
    )

    return AgentConfig(
        api_base_url=str(api_base_url).strip().rstrip("/"),
        device_id=str(device_id).strip(),
        device_token=str(device_token).strip(),
        poll_interval_seconds=int(
            os.environ.get("TRAVELPORT_AGENT_POLL_INTERVAL")
            or payload.get("poll_interval_seconds", 15)
        ),
        heartbeat_interval_seconds=int(
            os.environ.get("TRAVELPORT_AGENT_HEARTBEAT_INTERVAL")
            or payload.get("heartbeat_interval_seconds", 20)
        ),
        upload_reports=_to_bool(
            os.environ.get("TRAVELPORT_AGENT_UPLOAD_REPORTS"),
            payload.get("upload_reports", True),
        ),
        upload_logs=_to_bool(
            os.environ.get("TRAVELPORT_AGENT_UPLOAD_LOGS"),
            payload.get("upload_logs", True),
        ),
        keep_local_reports=_to_bool(
            os.environ.get("TRAVELPORT_AGENT_KEEP_LOCAL_REPORTS"),
            payload.get("keep_local_reports", True),
        ),
        keep_local_logs=_to_bool(
            os.environ.get("TRAVELPORT_AGENT_KEEP_LOCAL_LOGS"),
            payload.get("keep_local_logs", True),
        ),
        stop_check_interval_seconds=int(
            os.environ.get("TRAVELPORT_AGENT_STOP_CHECK_INTERVAL")
            or payload.get("stop_check_interval_seconds", 5)
        ),
    )


def _to_bool(env_value, fallback) -> bool:
    if env_value is None:
        return bool(fallback)
    return str(env_value).strip().lower() in {"1", "true", "yes", "on"}
