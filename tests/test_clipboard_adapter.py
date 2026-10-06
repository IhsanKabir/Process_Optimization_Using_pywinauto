"""Tests for the _Clipboard fallback chain in smartpoint_automation."""

import logging

import smartpoint_automation as spa


class _FailingPyperclip:
    def copy(self, text):
        raise RuntimeError("locked")

    def paste(self):
        raise RuntimeError("locked")


class _WorkingPyperclip:
    def paste(self):
        return "FALLBACK TEXT"


def _boom(*_args):
    raise OSError("clipboard busy")


def test_paste_falls_back_to_pyperclip(monkeypatch):
    monkeypatch.setattr(spa, "clipboard_paste", _boom)
    monkeypatch.setattr(spa, "_real_pyperclip", _WorkingPyperclip())

    assert spa._Clipboard.paste() == "FALLBACK TEXT"


def test_paste_logs_warning_when_every_backend_fails(monkeypatch, caplog):
    monkeypatch.setattr(spa, "clipboard_paste", _boom)
    monkeypatch.setattr(spa, "_real_pyperclip", _FailingPyperclip())

    with caplog.at_level(logging.DEBUG, logger="travelport.automation"):
        assert spa._Clipboard.paste() == ""

    messages = [r.getMessage() for r in caplog.records]
    assert any("paste failed, trying pyperclip" in m for m in messages)
    assert any(
        r.levelno == logging.WARNING and "pyperclip paste failed" in r.getMessage()
        for r in caplog.records
    )


def test_copy_logs_warning_when_every_backend_fails(monkeypatch, caplog):
    monkeypatch.setattr(spa, "clipboard_copy", _boom)
    monkeypatch.setattr(spa, "_real_pyperclip", _FailingPyperclip())

    with caplog.at_level(logging.WARNING, logger="travelport.automation"):
        spa._Clipboard.copy("X")

    assert "pyperclip copy failed" in caplog.text
