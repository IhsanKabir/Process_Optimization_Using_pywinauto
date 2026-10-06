"""Automatic Smartpoint sign-on is opt-in (SMARTPOINT_AUTO_LOGIN)."""

import pytest

import main


class _FakeAutomation:
    def __init__(self, succeeds=True):
        self.succeeds = succeeds
        self.calls = []

    def login(self, username, password, pcc):
        self.calls.append((username, password, pcc))
        return self.succeeds


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in (
        "SMARTPOINT_AUTO_LOGIN",
        "SMARTPOINT_SKIP_AUTO_LOGIN",
        "SMARTPOINT_USERNAME",
        "SMARTPOINT_PASSWORD",
        "SMARTPOINT_PCC",
    ):
        monkeypatch.delenv(name, raising=False)


def _set_credentials(monkeypatch):
    monkeypatch.setenv("SMARTPOINT_USERNAME", "agent01")
    monkeypatch.setenv("SMARTPOINT_PASSWORD", "stale-pass")
    monkeypatch.setenv("SMARTPOINT_PCC", "3L5Q")


def test_credentials_alone_do_not_trigger_sign_on(monkeypatch):
    _set_credentials(monkeypatch)
    automation = _FakeAutomation()

    assert main._auto_login_if_enabled(automation) is True
    assert automation.calls == []


def test_opt_in_signs_on_with_credentials(monkeypatch):
    _set_credentials(monkeypatch)
    monkeypatch.setenv("SMARTPOINT_AUTO_LOGIN", "1")
    automation = _FakeAutomation()

    assert main._auto_login_if_enabled(automation) is True
    assert automation.calls == [("agent01", "stale-pass", "3L5Q")]


def test_opt_in_reports_failed_sign_on(monkeypatch):
    _set_credentials(monkeypatch)
    monkeypatch.setenv("SMARTPOINT_AUTO_LOGIN", "true")

    assert main._auto_login_if_enabled(_FakeAutomation(succeeds=False)) is False


def test_skip_flag_still_wins(monkeypatch):
    _set_credentials(monkeypatch)
    monkeypatch.setenv("SMARTPOINT_AUTO_LOGIN", "1")
    monkeypatch.setenv("SMARTPOINT_SKIP_AUTO_LOGIN", "1")
    automation = _FakeAutomation()

    assert main._auto_login_if_enabled(automation) is True
    assert automation.calls == []


def test_opt_in_without_credentials_uses_existing_session(monkeypatch):
    monkeypatch.setenv("SMARTPOINT_AUTO_LOGIN", "1")
    automation = _FakeAutomation()

    assert main._auto_login_if_enabled(automation) is True
    assert automation.calls == []
