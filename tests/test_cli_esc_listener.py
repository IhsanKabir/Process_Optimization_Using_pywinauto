"""The CLI ESC listener must ignore the automation's own Escape key presses."""

import ctypes
import logging
import threading
import time

import pytest

import main


class _FakeUser32:
    def __init__(self, states):
        self._states = iter(states)

    def GetAsyncKeyState(self, _vk):
        return next(self._states, 0)


def _run_listener(monkeypatch, states):
    monkeypatch.setattr(
        ctypes, "windll", type("W", (), {"user32": _FakeUser32(states)})()
    )
    monkeypatch.setattr(time, "sleep", lambda s: None)
    stop = threading.Event()
    main._install_cli_esc_listener(stop, logging.getLogger("test"))
    stop.wait(timeout=1.0)
    return stop.is_set()


DOWN, UP = 0x8000, 0


@pytest.mark.skipif(not hasattr(ctypes, "WinDLL"), reason="Windows only")
def test_brief_synthetic_escape_does_not_stop(monkeypatch):
    # The copy routine's Escape press shows up for a single 0.1 s poll.
    assert not _run_listener(monkeypatch, [UP, DOWN, UP, UP, DOWN, UP] + [UP] * 50)


@pytest.mark.skipif(not hasattr(ctypes, "WinDLL"), reason="Windows only")
def test_held_escape_stops(monkeypatch):
    assert _run_listener(monkeypatch, [UP, DOWN, DOWN, DOWN, DOWN])
