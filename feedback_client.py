"""
feedback_client.py - Submit end-user feedback to the website/admin backend.
"""

from __future__ import annotations

import json
import platform
import socket
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from agent_config import AgentConfig, load_agent_config


class FeedbackSubmissionError(RuntimeError):
    """Raised when feedback cannot be delivered to the backend."""


def build_feedback_payload(
    *,
    category: str,
    subject: str,
    message: str,
    app_version: str,
    context: dict[str, Any] | None = None,
    config: AgentConfig | None = None,
) -> dict[str, Any]:
    """Build the feedback payload sent to the backend."""
    clean_subject = (subject or "").strip()
    clean_message = (message or "").strip()
    clean_category = (category or "general").strip().lower()

    if not clean_subject:
        raise FeedbackSubmissionError("Please enter a short subject.")
    if not clean_message:
        raise FeedbackSubmissionError("Please enter your feedback message.")

    agent = config or load_agent_config()

    return {
        "category": clean_category,
        "subject": clean_subject,
        "message": clean_message,
        "app_version": (app_version or "").strip(),
        "device_id": agent.device_id,
        "device_name": socket.gethostname(),
        "hostname": socket.gethostname(),
        "os_version": platform.platform(),
        "source": "desktop_gui",
        "submitted_at_utc": datetime.now(timezone.utc).isoformat(),
        "context": context or {},
    }


def submit_feedback(
    *,
    category: str,
    subject: str,
    message: str,
    app_version: str,
    context: dict[str, Any] | None = None,
    config: AgentConfig | None = None,
) -> dict[str, Any]:
    """Send feedback to the configured backend feedback endpoint."""
    agent = config or load_agent_config()
    if not agent.api_base_url:
        raise FeedbackSubmissionError(
            "Feedback delivery is not configured on this machine yet."
        )

    payload = build_feedback_payload(
        category=category,
        subject=subject,
        message=message,
        app_version=app_version,
        context=context,
        config=agent,
    )

    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{agent.api_base_url.rstrip('/')}/feedback",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": f"TravelportAuto/{app_version or 'unknown'}",
        },
    )
    if agent.device_token:
        request.add_header("Authorization", f"Bearer {agent.device_token}")

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read().decode("utf-8", errors="replace").strip()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        raise FeedbackSubmissionError(
            f"Server rejected the feedback ({exc.code}). {detail[:200]}"
        ) from exc
    except urllib.error.URLError as exc:
        raise FeedbackSubmissionError(
            f"Could not send feedback to admin: {exc.reason}"
        ) from exc

    if not raw:
        return {"ok": True}

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"ok": True, "raw_response": raw}
