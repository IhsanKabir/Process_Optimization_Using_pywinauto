"""Helpers shared by the D and BOOK click fan-outs."""

import smartpoint_automation as spa
from smartpoint_automation import (
    SmartpointAutomation,
    _prioritise_offsets,
    _saved_offset_variants,
)


class _Rect:
    def width(self):
        return 700


def test_prioritise_offsets_moves_first_to_front_without_duplicates():
    offsets = [(0, 0), (15, 0), (-15, 0)]

    assert _prioritise_offsets([(15, 0), (3, 3)], offsets) == [
        (15, 0),
        (3, 3),
        (0, 0),
        (-15, 0),
    ]


def test_saved_offset_variants_keep_column_and_nudge_rows():
    assert _saved_offset_variants(12, -4) == [
        (12, -4),
        (12, 0),
        (12, -9),
        (12, 9),
        (12, -18),
        (12, 18),
    ]


def _automation(monkeypatch, cal):
    automation = SmartpointAutomation()
    automation._cal = cal
    monkeypatch.setattr(automation, "_get_terminal_rect", lambda: _Rect())
    saved = []
    monkeypatch.setattr(spa._calibration_mod, "save_calibration", saved.append)
    return automation, saved


def test_book_offset_prefers_char_x_anchor(monkeypatch):
    automation, _ = _automation(
        monkeypatch, {"book_click_offset": [5, 0], "book_click_char_x_offset": [2, 1]}
    )

    saved, saved_char_x, effective = automation._load_saved_click_offset(
        "book", "BOOK", char_x=110, base_x=100
    )

    assert saved == (5, 0) and saved_char_x == (2, 1)
    assert effective == (12, 1)  # (char_x - base_x) + 2, y 1


def test_absurd_book_offset_is_cleared(monkeypatch):
    automation, saved = _automation(monkeypatch, {"book_click_offset": [-554, -385]})

    result = automation._load_saved_click_offset("book", "BOOK", None, 100)

    assert result == (None, None, None)
    assert "book_click_offset" not in automation._cal
    assert saved  # calibration file rewritten without the bad offset
