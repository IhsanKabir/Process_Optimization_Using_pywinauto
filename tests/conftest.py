import pytest


@pytest.fixture(autouse=True)
def _no_real_screen_capture(monkeypatch):
    """Tests must never screenshot the developer's real desktop.

    Tests that exercise screen-located clicks patch _grab_terminal_image with a
    fixture image instead.
    """
    import smartpoint_automation as spa

    monkeypatch.setattr(
        spa.SmartpointAutomation, "_grab_terminal_image", lambda self, rect: None
    )
