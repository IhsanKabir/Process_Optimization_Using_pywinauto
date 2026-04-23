"""
feedback_queue.py - Offline queue for feedback payloads that could not be sent.

Layout: %APPDATA%\\TravelportAuto\\feedback_queue.json
  A JSON array of raw payload dicts (the same dicts submit_feedback would POST).
  Cap: 50 entries — oldest are dropped when the cap is exceeded.
  Flush: attempted on app startup (drain_feedback_queue) and after every
  successful live submit (drain_feedback_queue can be called at any time).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_QUEUE_CAP = 50


def _queue_path() -> Path:
    appdata = os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming"
    return Path(appdata) / "TravelportAuto" / "feedback_queue.json"


def _load_queue() -> list[dict[str, Any]]:
    path = _queue_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError):
        logger.warning("feedback_queue: corrupted queue file; starting fresh")
    return []


def _save_queue(entries: list[dict[str, Any]]) -> None:
    path = _queue_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def enqueue_feedback(payload: dict[str, Any]) -> None:
    """Append a payload to the offline queue, enforcing the cap."""
    entries = _load_queue()
    entries.append(payload)
    if len(entries) > _QUEUE_CAP:
        entries = entries[-_QUEUE_CAP:]  # drop oldest
    _save_queue(entries)
    logger.info("feedback_queue: queued payload (queue size=%d)", len(entries))


def drain_feedback_queue(submit_fn) -> tuple[int, int]:
    """Try to submit all queued payloads via *submit_fn(payload)*.

    *submit_fn* must accept a single dict and raise on failure.
    Returns (sent, remaining) counts.
    """
    entries = _load_queue()
    if not entries:
        return 0, 0

    remaining: list[dict[str, Any]] = []
    sent = 0
    for entry in entries:
        try:
            submit_fn(entry)
            sent += 1
        except Exception:
            remaining.append(entry)

    _save_queue(remaining)
    if sent:
        logger.info("feedback_queue: drained %d item(s); %d remaining", sent, len(remaining))
    return sent, len(remaining)
