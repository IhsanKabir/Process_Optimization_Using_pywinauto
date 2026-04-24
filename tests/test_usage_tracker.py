"""
Tests for usage_tracker — daily run counters for passive demand telemetry.
"""

from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path

import pytest


def _make_temp_dir() -> Path:
    """Create a unique temp dir under cwd to avoid Windows %TEMP% permission issues."""
    import uuid
    d = Path.cwd() / f"tmp_test_usage_{uuid.uuid4().hex[:8]}"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """Redirect APPDATA to a local temp dir and reload usage_tracker fresh each test."""
    import sys
    import shutil

    tmp = _make_temp_dir()
    monkeypatch.setenv("APPDATA", str(tmp))

    # Remove cached module so _stats_path() picks up the patched env var
    sys.modules.pop("usage_tracker", None)
    yield
    sys.modules.pop("usage_tracker", None)
    shutil.rmtree(tmp, ignore_errors=True)


def _load_raw(appdata_root: str) -> dict:
    path = Path(appdata_root) / "TravelportAuto" / "usage_stats.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def test_increment_creates_file(monkeypatch):
    from usage_tracker import increment
    appdata = os.environ["APPDATA"]
    increment("fare_routes")
    data = _load_raw(appdata)
    today = date.today().isoformat()
    assert data[today]["fare_routes"] == 1


def test_increment_accumulates(monkeypatch):
    from usage_tracker import increment
    appdata = os.environ["APPDATA"]
    increment("fare_routes", 3)
    increment("fare_routes", 2)
    data = _load_raw(appdata)
    today = date.today().isoformat()
    assert data[today]["fare_routes"] == 5


def test_all_metrics_tracked_independently(monkeypatch):
    from usage_tracker import increment
    appdata = os.environ["APPDATA"]
    increment("fare_routes", 5)
    increment("ftax_airports", 3)
    increment("penalty_runs", 1)
    increment("currency_runs", 2)
    data = _load_raw(appdata)
    today = date.today().isoformat()
    assert data[today]["fare_routes"] == 5
    assert data[today]["ftax_airports"] == 3
    assert data[today]["penalty_runs"] == 1
    assert data[today]["currency_runs"] == 2


def test_invalid_metric_ignored(monkeypatch):
    from usage_tracker import increment
    appdata = os.environ["APPDATA"]
    increment("not_a_real_metric")
    # File may not even exist
    data = _load_raw(appdata)
    assert data == {}


def test_get_today_context_returns_zeros_when_empty():
    from usage_tracker import get_today_context
    ctx = get_today_context()
    assert ctx["usage_fare_routes_today"] == 0
    assert ctx["usage_ftax_airports_today"] == 0
    assert ctx["usage_penalty_runs_today"] == 0
    assert ctx["usage_currency_runs_today"] == 0
    assert ctx["usage_days_active_30d"] == 0


def test_get_today_context_reflects_increments():
    from usage_tracker import get_today_context, increment
    increment("fare_routes", 7)
    increment("penalty_runs", 2)
    ctx = get_today_context()
    assert ctx["usage_fare_routes_today"] == 7
    assert ctx["usage_penalty_runs_today"] == 2
    assert ctx["usage_days_active_30d"] == 1


def test_days_active_counts_distinct_days(monkeypatch):
    """Seed two past days + today and confirm days_active_30d == 3."""
    from usage_tracker import increment, get_today_context, _stats_path
    import importlib
    import usage_tracker as ut

    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    two_days_ago = (date.today() - timedelta(days=2)).isoformat()

    seed = {
        yesterday: {"fare_routes": 4, "ftax_airports": 0, "penalty_runs": 0, "currency_runs": 0},
        two_days_ago: {"fare_routes": 0, "ftax_airports": 2, "penalty_runs": 0, "currency_runs": 0},
    }
    path = ut._stats_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(seed))

    increment("fare_routes", 1)
    ctx = get_today_context()
    assert ctx["usage_days_active_30d"] == 3


def test_prune_drops_old_entries(monkeypatch):
    """Entries older than 30 days are pruned on next increment."""
    import usage_tracker as ut

    old_day = (date.today() - timedelta(days=31)).isoformat()
    recent_day = (date.today() - timedelta(days=5)).isoformat()

    seed = {
        old_day: {"fare_routes": 10, "ftax_airports": 0, "penalty_runs": 0, "currency_runs": 0},
        recent_day: {"fare_routes": 3, "ftax_airports": 0, "penalty_runs": 0, "currency_runs": 0},
    }
    path = ut._stats_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(seed))

    from usage_tracker import increment
    increment("fare_routes")

    data = _load_raw(os.environ["APPDATA"])
    assert old_day not in data
    assert recent_day in data


def test_malformed_json_does_not_crash():
    import usage_tracker as ut
    path = ut._stats_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{{not valid json")

    from usage_tracker import increment, get_today_context
    increment("fare_routes")  # should not raise
    ctx = get_today_context()
    assert ctx["usage_fare_routes_today"] == 1


def test_usage_injected_into_feedback_payload(monkeypatch):
    """get_today_context() values appear in the feedback context automatically."""
    from usage_tracker import increment
    increment("fare_routes", 3)

    import sys
    # Patch keyring so feedback_client loads cleanly
    import types
    fake_kr = types.ModuleType("keyring")
    fake_kr.get_password = lambda *a: None
    fake_kr.errors = types.SimpleNamespace(PasswordDeleteError=Exception)
    sys.modules["keyring"] = fake_kr

    from agent_config import AgentConfig
    from feedback_client import build_feedback_payload

    payload = build_feedback_payload(
        category="bug",
        subject="Test subject",
        message="Test message body",
        app_version="v1.0.0",
        config=AgentConfig(api_base_url="https://x.com", device_token="dt", device_id="d1"),
    )
    ctx = payload["context"]
    assert ctx["usage_fare_routes_today"] == 3
    assert "usage_days_active_30d" in ctx

    sys.modules.pop("keyring", None)
