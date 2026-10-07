"""SmartpointAutomation clicks that locate their target from a screenshot.

Uses the real FS screenshot fixture (terminal renders at 14 px per line while
the calibrated model assumes 20 px), placed at a fake terminal rect.
"""

import os

from PIL import Image

import smartpoint_automation as spa
from smartpoint_automation import SmartpointAutomation

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "fs_options_terminal.png")
RECT_LEFT, RECT_TOP = 1340, 95

FS_TEXT = "\n".join(
    [
        ">",
        "",
        "TTL OF 4   PRICING OPTIONS AND 13    ITINERARY OPTIONS RETURNED",
        "",
        "PRICING OPTION 1                  TOTAL AMOUNT          34797 BDT",
        "ADT                               TAX INCLUDED",
        "1   BS    205  I  12NOV DAC MAA   1045  1255    TH   738    IBMAAO",
        "2   UL    128  S  12NOV MAA CMB   1555  1715    TH   320     SOWIZ",
        "3   UL    225  S  12NOV CMB DXB   1840  2150    TH   332     SOWIZ",
        "\xabBOOK\xbb    +TQ                                         D  R  +5",
        "",
        "PRICING OPTION 2                  TOTAL AMOUNT          36649 BDT",
        "ADT                               TAX INCLUDED",
        "1   BS    343  S  12NOV DAC1DXB   0630  1155    TH   738    SBDXBO",
        "\xabBOOK\xbb    +TQ                                         D  R",
        "",
        "PRICING OPTION 3                  TOTAL AMOUNT          36649 BDT",
        "ADT                               TAX INCLUDED",
        "1   BS    341  S  12NOV DAC DXB   1710  2045    TH   738    SBDXBO",
        "\xabBOOK\xbb    +TQ                                         D  R",
        "",
        "PRICING OPTION 4                  TOTAL AMOUNT          55474 BDT",
        "ADT                               TAX INCLUDED",
        "1   BG    617  Y  12NOV DAC CGP   2100  2200    TH   DH8       YOW",
        "2   BS    343  K  13NOV CGP DXB   0815  1155    FR   738    KBDXBO",
        "\xabBOOK\xbb    +TQ                                         D  R  +4",
        "",
        ">",
    ]
)

TAX_SCREEN = (
    "TOTAL JOURNEY TIME\nFS-3 ADT\nREFUNDABLE: NO\nFARE BDT1 TAXES BDT2 TOT BDT3"
)


class _Rect:
    def __init__(self, img):
        self.left, self.top = RECT_LEFT, RECT_TOP
        self.right, self.bottom = RECT_LEFT + img.width, RECT_TOP + img.height

    def width(self):
        return self.right - self.left

    def height(self):
        return self.bottom - self.top


def _automation(monkeypatch, response):
    img = Image.open(FIXTURE).convert("RGB")
    automation = SmartpointAutomation()
    rect = _Rect(img)
    clicks = []

    monkeypatch.setattr(automation, "focus", lambda force=False: True)
    monkeypatch.setattr(automation, "_get_terminal_rect", lambda: rect)
    monkeypatch.setattr(automation, "_grab_terminal_image", lambda r: img)
    monkeypatch.setattr(automation, "_wait_for_response", lambda *a, **k: response)
    monkeypatch.setattr(automation, "_wait_for_stable_screen", lambda *a, **k: response)
    monkeypatch.setattr(spa.pyautogui, "press", lambda *a, **k: None)
    monkeypatch.setattr(
        spa.pyautogui, "moveTo", lambda x, y, **k: clicks.append((x, y))
    )
    monkeypatch.setattr(spa.pyautogui, "click", lambda *a, **k: None)
    monkeypatch.setattr(spa.time, "sleep", lambda s: None)
    saved = []
    monkeypatch.setattr(spa._calibration_mod, "save_calibration", saved.append)
    return automation, clicks, saved


def test_d_click_hits_screen_located_d_on_first_attempt(monkeypatch):
    automation, clicks, saved = _automation(monkeypatch, TAX_SCREEN)

    result = automation.click_d_button(2, FS_TEXT)

    assert "FS-3 ADT" in result
    assert len(clicks) == 1
    x, y = clicks[0]
    # Option 3's D on the fixture: (443, 271) + rect origin.
    assert abs(x - (RECT_LEFT + 443)) <= 4 and abs(y - (RECT_TOP + 271)) <= 4
    assert saved == []  # a screen-located hit must not rewrite calibration


def _long_fs_text(option_count):
    """FS output taller than the 65-line fixture terminal."""
    lines = [">", ""] + [f"FILLER {i}" for i in range(50)]
    for n in range(1, option_count + 1):
        lines += [
            f"PRICING OPTION {n}                  TOTAL AMOUNT          34797 BDT",
            "ADT                               TAX INCLUDED",
            "1   BS    205  I  12NOV DAC MAA   1045  1255    TH   738    IBMAAO",
            "\xabBOOK\xbb    +TQ                                         D  R",
            "",
        ]
    return "\n".join(lines + [">"])


def test_d_click_scrolls_to_bottom_for_option_below_the_fold(monkeypatch):
    automation, clicks, _ = _automation(monkeypatch, TAX_SCREEN.replace("FS-3", "FS-6"))
    pressed = []
    monkeypatch.setattr(spa.pyautogui, "press", lambda key, **k: pressed.append(key))
    monkeypatch.setattr(automation, "_get_terminal_focus_point", lambda: (1500, 900))
    monkeypatch.setattr(automation, "_safe_focus_click", lambda x, y: None)

    # 6 options; after PageDown the fixture shows the last four, so option 6
    # is the fixture's last row (D at 443, 355).
    automation.click_d_button(5, _long_fs_text(6))

    assert "pagedown" in pressed
    x, y = clicks[0]
    assert abs(x - (RECT_LEFT + 443)) <= 4 and abs(y - (RECT_TOP + 355)) <= 4


def test_book_click_hits_screen_located_book(monkeypatch):
    automation, clicks, _ = _automation(monkeypatch, "BOOKING CONTEXT SCREEN")

    result = automation.click_book_link(1, FS_TEXT)

    assert result == "BOOKING CONTEXT SCREEN"
    x, y = clicks[0]
    assert x < RECT_LEFT + 80
    assert abs(y - (RECT_TOP + 201)) <= 4


def test_line_to_pixel_uses_measured_pitch(monkeypatch):
    automation, _, _ = _automation(monkeypatch, "")
    automation._line_height = 20  # stale calibration

    _, y = automation._text_line_to_pixel(FS_TEXT, 19)

    # Option 3 BOOK row renders at y=271 in the fixture, not 95 + 5 + 19.5*20.
    assert abs(y - (RECT_TOP + 271)) <= 4


def test_falls_back_to_calibration_without_screen(monkeypatch):
    automation, _, _ = _automation(monkeypatch, "")
    monkeypatch.setattr(automation, "_grab_terminal_image", lambda r: None)
    automation._line_height = 20
    automation._content_top_padding = 5

    _, y = automation._text_line_to_pixel(FS_TEXT, 9)

    assert y == int(RECT_TOP + 5 + 9.5 * 20)


def test_row_count_mismatch_saves_screenshot_beside_run_log(monkeypatch, tmp_path):
    import logging

    automation, clicks, _ = _automation(monkeypatch, TAX_SCREEN)
    handler = logging.FileHandler(tmp_path / "run_test.log")
    logging.getLogger("travelport").addHandler(handler)
    extra_option = FS_TEXT.replace(
        "\n>",
        "\nPRICING OPTION 5\nADT\n1   BS 1\n\xabBOOK\xbb    +TQ    D  R\n\n>",
    )
    try:
        automation.click_d_button(2, extra_option)
    finally:
        logging.getLogger("travelport").removeHandler(handler)
        handler.close()

    saved = list(tmp_path.glob("screen_*_option3_rows4.png"))
    assert len(saved) == 1
    assert clicks  # fell back to the predicted position
