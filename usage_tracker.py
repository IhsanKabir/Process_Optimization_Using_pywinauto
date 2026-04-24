"""
usage_tracker.py — Daily run counters for passive demand telemetry.

Tracks how many fare/tax/penalty/currency runs happen per day, persisted in
%APPDATA%/TravelportAuto/usage_stats.json.  Counts are included automatically
in any feedback submission so demand evidence accumulates without a dedicated
telemetry endpoint.

No PII is stored — all values are plain integers or dates.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

_METRICS = ("fare_routes", "ftax_airports", "penalty_runs", "currency_runs")
_RETENTION_DAYS = 30
_lock = threading.Lock()


def _stats_path() -> Path:
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / "TravelportAuto" / "usage_stats.json"


def _load() -> dict[str, Any]:
    path = _stats_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(data: dict[str, Any]) -> None:
    path = _stats_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _prune(data: dict[str, Any]) -> dict[str, Any]:
    """Drop entries older than _RETENTION_DAYS days."""
    today = date.today()
    pruned = {}
    for day_str, counts in data.items():
        try:
            day = date.fromisoformat(day_str)
            if (today - day).days <= _RETENTION_DAYS:
                pruned[day_str] = counts
        except ValueError:
            pass
    return pruned


def _today() -> str:
    return date.today().isoformat()


def increment(metric: str, count: int = 1) -> None:
    """Increment a daily counter.  Silently swallows all errors."""
    if metric not in _METRICS:
        return
    try:
        with _lock:
            data = _prune(_load())
            today = _today()
            day_entry = data.setdefault(today, {m: 0 for m in _METRICS})
            day_entry[metric] = day_entry.get(metric, 0) + count
            _save(data)
    except Exception:
        pass


def get_today_context() -> dict[str, Any]:
    """Return today's counters + 30-day active-days count, ready for feedback context."""
    try:
        with _lock:
            data = _prune(_load())
        today = _today()
        today_entry = data.get(today, {})
        days_active = sum(
            1 for d in data.values()
            if any(d.get(m, 0) > 0 for m in _METRICS)
        )
        return {
            "usage_fare_routes_today": today_entry.get("fare_routes", 0),
            "usage_ftax_airports_today": today_entry.get("ftax_airports", 0),
            "usage_penalty_runs_today": today_entry.get("penalty_runs", 0),
            "usage_currency_runs_today": today_entry.get("currency_runs", 0),
            "usage_days_active_30d": days_active,
        }
    except Exception:
        return {}
