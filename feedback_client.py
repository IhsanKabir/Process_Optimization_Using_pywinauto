"""
feedback_client.py - Submit end-user feedback to the website/admin backend.

Failure handling:
  - URLError / timeout   → queued for retry on next launch (network issue)
  - HTTPError 4xx        → rejected without retry; server message surfaced to user
  - HTTPError 5xx        → queued for retry; user warned of server error
"""

from __future__ import annotations

import json
import platform
import re
import socket
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from agent_config import AgentConfig, load_agent_config

_PII_KEY_PATTERN = re.compile(
    r"pass(word)?|pwd|token|secret|key|auth|cred", re.IGNORECASE
)
_PATH_PATTERN = re.compile(r"[A-Za-z]:\\|/home/|/Users/")


def _scrub_context(context: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of context with PII-bearing values replaced by [REDACTED]."""
    scrubbed: dict[str, Any] = {}
    for k, v in context.items():
        if _PII_KEY_PATTERN.search(str(k)):
            scrubbed[k] = "[REDACTED]"
        elif isinstance(v, str) and _PATH_PATTERN.search(v):
            scrubbed[k] = "[REDACTED]"
        else:
            scrubbed[k] = v
    return scrubbed


class FeedbackSubmissionError(RuntimeError):
    """Raised when feedback cannot be delivered to the backend."""


class FeedbackQueuedForRetry(Exception):
    """Raised when the payload was queued locally and will retry on next launch."""


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
        "context": _scrub_context(context or {}),
    }


def _resolve_session_token() -> str | None:
    """Return the user session token from keyring → env var, or None."""
    try:
        from auth_manager import get_token
        token = get_token()
        if token:
            return token
    except Exception:
        pass
    import os
    return os.environ.get("TRAVELPORT_USER_TOKEN") or None


def submit_feedback(
    *,
    category: str,
    subject: str,
    message: str,
    app_version: str,
    context: dict[str, Any] | None = None,
    config: AgentConfig | None = None,
    user_session_token: str | None = None,
) -> dict[str, Any]:
    """Send feedback to the configured backend feedback endpoint.

    Auth preference: user session token (keyring / env / explicit arg) >
    device token (agent_config). Device-id is always included in the payload
    for telemetry continuity regardless of which auth method is used.

    Raises:
        FeedbackSubmissionError: Validation error or unrecoverable 4xx from server.
        FeedbackQueuedForRetry: Network error or 5xx — payload saved to offline queue.
    """
    from feedback_queue import enqueue_feedback

    agent = config or load_agent_config()

    payload = build_feedback_payload(
        category=category,
        subject=subject,
        message=message,
        app_version=app_version,
        context=context,
        config=agent,
    )

    session_token = user_session_token or _resolve_session_token()

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
    if session_token:
        request.add_header("X-User-Session", session_token)
    elif agent.device_token:
        request.add_header("Authorization", f"Bearer {agent.device_token}")

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read().decode("utf-8", errors="replace").strip()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        if exc.code >= 500:
            enqueue_feedback(payload)
            raise FeedbackQueuedForRetry(
                f"Server error ({exc.code}). Your feedback was saved and will be "
                "resent on next launch."
            ) from exc
        raise FeedbackSubmissionError(
            f"Server rejected the feedback ({exc.code}). {detail[:200]}"
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        enqueue_feedback(payload)
        raise FeedbackQueuedForRetry(
            "Could not reach the server. Your feedback was saved and will be "
            "resent on next launch."
        ) from exc

    if not raw:
        return {"ok": True}

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"ok": True, "raw_response": raw}
