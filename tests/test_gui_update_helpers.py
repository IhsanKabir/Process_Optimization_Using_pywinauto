from gui import (
    _build_update_notice,
    _escape_hold_state,
    _estimate_remaining_seconds,
    _format_eta_seconds,
    _pick_release_exe_url,
)


def test_pick_release_exe_url_prefers_primary_travelport_exe():
    assets = [
        {
            "name": "TravelportAuto_update.exe",
            "browser_download_url": "https://example.com/update.exe",
        },
        {
            "name": "TravelportAuto.exe",
            "browser_download_url": "https://example.com/app.exe",
        },
    ]

    assert _pick_release_exe_url(assets) == "https://example.com/app.exe"


def test_build_update_notice_warns_when_old_version_is_still_running(monkeypatch):
    pending_exe = r"C:\test\TravelportAuto_update.exe"
    monkeypatch.setattr(
        "gui.os.path.exists",
        lambda path: path == pending_exe,
    )

    notice = _build_update_notice(
        "v1.4.0",
        {
            "status": "failed",
            "version": "v1.4.1",
            "message": "Windows could not replace TravelportAuto.exe automatically.",
        },
        pending_exe,
    )

    assert notice is not None
    assert notice["title"] == "Update Needs Manual Replace"
    assert "still running v1.4.0" in notice["message"]
    assert "TravelportAuto_update.exe" in notice["message"]


def test_build_update_notice_is_none_after_new_version_is_running(monkeypatch):
    pending_exe = r"C:\test\TravelportAuto_update.exe"
    monkeypatch.setattr("gui.os.path.exists", lambda path: False)

    notice = _build_update_notice(
        "v1.4.1",
        {
            "status": "installed",
            "version": "v1.4.1",
            "message": "Update installed successfully.",
        },
        pending_exe,
    )

    assert notice is None


def test_estimate_remaining_seconds_uses_completed_average():
    assert _estimate_remaining_seconds(120, completed=2, total=5) == 180


def test_estimate_remaining_seconds_returns_none_without_progress():
    assert _estimate_remaining_seconds(120, completed=0, total=5) is None


def test_format_eta_seconds_formats_minutes_and_seconds():
    assert _format_eta_seconds(125) == "2m 05s"


def test_escape_hold_state_ignores_quick_escape_tap():
    pressed_since, should_stop = _escape_hold_state(
        True, now=10.0, pressed_since=None, hold_seconds=0.8
    )
    assert pressed_since == 10.0
    assert should_stop is False

    pressed_since, should_stop = _escape_hold_state(
        True, now=10.2, pressed_since=pressed_since, hold_seconds=0.8
    )
    assert pressed_since == 10.0
    assert should_stop is False


def test_escape_hold_state_stops_after_deliberate_hold():
    pressed_since, should_stop = _escape_hold_state(
        True, now=10.9, pressed_since=10.0, hold_seconds=0.8
    )
    assert pressed_since == 10.0
    assert should_stop is True


def test_escape_hold_state_resets_when_released():
    pressed_since, should_stop = _escape_hold_state(
        False, now=10.9, pressed_since=10.0, hold_seconds=0.8
    )
    assert pressed_since is None
    assert should_stop is False
