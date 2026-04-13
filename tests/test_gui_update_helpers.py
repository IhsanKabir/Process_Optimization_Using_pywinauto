from gui import _build_update_notice, _pick_release_exe_url


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
