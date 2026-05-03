import threading

import calibration
import smartpoint_automation as spa
from smartpoint_automation import SmartpointAutomation
from tax_breakdown_parser import (
    looks_like_fs_tax_breakdown,
    parse_fs_tax_breakdown,
)


def test_connect_falls_back_to_visible_galileo_desktop_alias(monkeypatch):
    connect_calls = []

    class FakeCandidate:
        def __init__(self, title):
            self._title = title

        def exists(self):
            return bool(self._title)

        def window_text(self):
            return self._title

    class FakeVisibleWindow(FakeCandidate):
        def __init__(self, title, handle):
            super().__init__(title)
            self.element_info = type("ElementInfo", (), {"handle": handle})()

    class FakeApp:
        def __init__(self, backend=None):
            self.backend = backend

        def connect(self, **kwargs):
            connect_calls.append(kwargs)
            if "handle" in kwargs:
                return self
            raise RuntimeError("not found")

        def window(self, **kwargs):
            if "handle" in kwargs:
                return FakeCandidate("Galileo Desktop - Window 1")
            return FakeCandidate("")

    class FakeDesktop:
        def __init__(self, backend=None):
            self.backend = backend

        def window(self, **kwargs):
            return FakeCandidate("")

        def windows(self):
            return [
                FakeVisibleWindow("TravelportAuto  v1.4.0", 10),
                FakeVisibleWindow("Galileo Desktop - Window 1", 42),
            ]

    monkeypatch.setattr(spa, "_PWApp", FakeApp)
    monkeypatch.setattr(spa, "Desktop", FakeDesktop)

    automation = SmartpointAutomation()

    assert automation.connect() is True
    assert automation.connected is True
    assert automation.window_title == "Galileo Desktop - Window 1"
    assert any(call.get("handle") == 42 for call in connect_calls)


def test_has_more_prompt_ignores_end_signal():
    automation = SmartpointAutomation()

    text = "PAGE 1\n\u00abMore Flights\u00bb\nEND\n>"

    assert automation._has_end_signal(text) is True
    assert automation._has_more_prompt(text) is False


def test_record_click_delta_does_not_mutate_global_line_height():
    cal = {
        "line_height": 20,
        "dpi": 96,
        "source": "dpi_auto",
        "click_deltas": [],
        "delta_correction": 0,
    }

    for _ in range(10):
        cal = calibration.record_click_delta(cal, -20)

    assert cal["line_height"] == 20
    assert cal["source"] == "dpi_auto"


def test_click_more_prompt_link_rereads_layout_after_scroll(monkeypatch):
    automation = SmartpointAutomation()
    # "More Flights" must have >= total_lines_capacity (9) lines after it so that
    # _bottom_base returns None (lines_from_bottom >= capacity), ensuring the
    # scroll fallback path actually fires.
    long_text = "\n".join(["ROW"] * 20 + ["          More Flights"] + ["ROW"] * 10)
    scrolled_text = "HEADER\n  More Flights\n>"
    next_page_text = "NEXT PAGE\nEND"
    copied_texts = iter([scrolled_text, next_page_text])
    moves = []
    presses = []

    class _Rect:
        left = 100
        top = 100
        right = 500
        bottom = 300

        def width(self):
            return self.right - self.left

        def height(self):
            return self.bottom - self.top

    monkeypatch.setattr(automation, "focus", lambda force=False: True)
    monkeypatch.setattr(automation, "_get_terminal_rect", lambda: _Rect())
    monkeypatch.setattr(automation, "_copy_terminal_text", lambda: next(copied_texts))
    monkeypatch.setattr(automation, "_has_dropdown_activated", lambda text: False)
    monkeypatch.setattr(spa.pyautogui, "click", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        spa.pyautogui,
        "moveTo",
        lambda x, y, duration=None: moves.append((x, y)),
    )
    monkeypatch.setattr(
        spa.pyautogui,
        "press",
        lambda key, *args, **kwargs: presses.append((key, kwargs.get("presses", 1))),
    )
    monkeypatch.setattr(spa.time, "sleep", lambda *args, **kwargs: None)

    assert automation.click_more_prompt_link(long_text) is True
    assert ("pagedown", 4) in presses
    assert moves[0][1] == 135


def test_run_command_waits_for_settled_end_before_sending_md(monkeypatch):
    automation = SmartpointAutomation()
    sent_commands = []

    monkeypatch.setattr(automation, "focus", lambda force=False: True)
    monkeypatch.setattr(automation, "_copy_terminal_text", lambda: "BEFORE")
    monkeypatch.setattr(
        automation,
        "_wait_for_response",
        lambda *args, **kwargs: "PAGE 1\n\u00abMore Flights\u00bb",
    )
    monkeypatch.setattr(
        automation, "_wait_for_stable_screen", lambda *args, **kwargs: "PAGE 1\nEND"
    )
    monkeypatch.setattr(automation, "_has_invalid", lambda text: False)
    monkeypatch.setattr(automation, "_has_currency_redirect", lambda text: None)
    monkeypatch.setattr(automation, "click_more_prompt_link", lambda text: False)

    monkeypatch.setattr(
        spa.pyautogui,
        "typewrite",
        lambda text, interval=None: sent_commands.append(text),
    )
    monkeypatch.setattr(spa.pyautogui, "press", lambda *args, **kwargs: None)

    result = automation.run_command("FDDACMCT/BG", max_pages=3)

    assert "END" in result
    assert "MD" not in sent_commands


def test_run_command_skips_extra_settle_when_initial_text_already_has_end(monkeypatch):
    automation = SmartpointAutomation()
    sent_commands = []
    settle_calls = []

    monkeypatch.setattr(automation, "focus", lambda force=False: True)
    monkeypatch.setattr(automation, "_copy_terminal_text", lambda: "BEFORE")
    monkeypatch.setattr(automation, "_wait_for_response", lambda *args, **kwargs: "PAGE 1\nEND")
    monkeypatch.setattr(
        automation,
        "_wait_for_stable_screen",
        lambda *args, **kwargs: settle_calls.append((args, kwargs)) or "SHOULD NOT RUN",
    )
    monkeypatch.setattr(automation, "_has_invalid", lambda text: False)
    monkeypatch.setattr(automation, "_has_currency_redirect", lambda text: None)
    monkeypatch.setattr(automation, "click_more_prompt_link", lambda text: False)

    monkeypatch.setattr(
        spa.pyautogui,
        "typewrite",
        lambda text, interval=None: sent_commands.append(text),
    )
    monkeypatch.setattr(spa.pyautogui, "press", lambda *args, **kwargs: None)

    result = automation.run_command("FDDACMCT/BG", max_pages=3)

    assert result == "PAGE 1\nEND"
    assert settle_calls == []
    assert "MD" not in sent_commands


def test_run_command_keeps_base_page_when_fu_expansion_is_unchanged(monkeypatch):
    automation = SmartpointAutomation()
    sent_commands = []
    base_page = (
        "MCTDAC\nUNSALEABLE FARES MAY EXIST\n  1  BG  360.00R  KBD6M    K\nEND"
    )
    responses = iter([base_page, base_page])

    monkeypatch.setattr(automation, "focus", lambda force=False: True)
    monkeypatch.setattr(automation, "_copy_terminal_text", lambda: base_page)
    monkeypatch.setattr(
        automation, "_wait_for_response", lambda *args, **kwargs: next(responses)
    )
    monkeypatch.setattr(
        automation,
        "_wait_for_stable_screen",
        lambda *args, **kwargs: "SHOULD NOT RUN",
    )
    monkeypatch.setattr(automation, "_has_invalid", lambda text: False)
    monkeypatch.setattr(automation, "_has_currency_redirect", lambda text: None)
    monkeypatch.setattr(automation, "click_more_prompt_link", lambda text: False)
    monkeypatch.setattr(
        spa.pyautogui,
        "typewrite",
        lambda text, interval=None: sent_commands.append(text),
    )
    monkeypatch.setattr(spa.pyautogui, "press", lambda *args, **kwargs: None)

    result = automation.run_command("FDMCTDAC/BG", max_pages=3)

    assert result == base_page
    assert "FU*" in sent_commands
    assert "MD" not in sent_commands
    assert "--- UNSALEABLE FARES BREAK ---" not in result


def test_looks_like_fs_tax_breakdown_accepts_bg_style_detail():
    text = """
TOTAL JOURNEY TIME

JED-DAC: 18:35

FS-1 ADT

REFUNDABLE: YES

LAST DATE TO PURCHASE TICKET: 21APR26 / 2359

PLATING CARRIER: BG BIMAN BANGLADESH AIRLINES

ADDITIONAL TAXES, SURCHARGES, OR FEES MAY APPLY

JED BG X/ZYL BG DAC M1057.60YOW NUC1057.60END ROE3.75

FARE SAR3966.00 EQU BDT129873 E3262 IO5240 T2164 YQ615  TAXES BDT6281  TOT BDT136154
"""

    parsed = parse_fs_tax_breakdown(text)

    assert looks_like_fs_tax_breakdown(text) is True
    assert parsed["equ_fare"] == 129873.0
    assert parsed["total_taxes"] == 6281.0
    assert parsed["exchange_rate"] > 0


def test_parse_fs_tax_breakdown_uses_default_rate_for_tax_only_text():
    text = "YQ246 TAXES BDT5375 TOT BDT27095"

    parsed = parse_fs_tax_breakdown(text)

    assert parsed["yq_charge"] == 246.0
    assert parsed["total_taxes"] == 5375.0
    assert parsed["total_amount"] == 27095.0
    assert parsed["exchange_rate"] == 1.0


# ── v1.5.17: Q-charge from fare-construction line + ROE parsing ───────────────


def test_parse_fs_tax_breakdown_extracts_q_charge_from_construction_line():
    """The Q surcharge appears in the IATA fare-construction line as
    'Q CITYORIG_CITYDEST AMOUNT'.  The amount is in NUC (= USD).  Captured
    as q_charge, ROE captured separately."""
    text = (
        "CAN CZ DAC 111.56Q2ASRSBU Q CANDAC28.97NUC140.53END ROE6.901808\n"
        "FARE CNY970 EQU BDT17459 CN1620 YQ492 YR7200  TAXES BDT9312  TOT BDT26771\n"
    )

    parsed = parse_fs_tax_breakdown(text)

    assert parsed["q_charge"] == 28.97  # NUC (USD)
    assert parsed["roe"] == 6.901808
    assert parsed["base_currency"] == "CNY"
    assert parsed["base_fare"] == 970.0
    assert parsed["equ_currency"] == "BDT"
    assert parsed["yq_charge"] == 492.0
    assert parsed["yr_charge"] == 7200.0


def test_parse_fs_tax_breakdown_q_charge_zero_when_no_construction_q():
    """When the fare construction line has no 'Q ORIGDEST' segment, q_charge
    must stay at 0.  The simpler USD-base example without Q must not
    accidentally pick up some other value."""
    text = (
        "DAC BG AUH 650.00DBDO NUC650.00END ROE1.0\n"
        "FARE USD650.00 EQU BDT79911 BD500 OW2500 P71230 P81230 UT4000 ZR168 E5444 YQ615  TAXES BDT10687  TOT BDT90598\n"
    )

    parsed = parse_fs_tax_breakdown(text)

    assert parsed["q_charge"] == 0.0
    assert parsed["roe"] == 1.0  # USD base
    assert parsed["yq_charge"] == 615.0


def test_parse_fs_tax_breakdown_roe_defaults_to_one_when_absent():
    """ROE absent in the captured text should default to 1.0 (USD-base
    convention)."""
    text = "FARE USD500 EQU BDT60000 TAXES BDT10000 TOT BDT70000"

    parsed = parse_fs_tax_breakdown(text)

    assert parsed["roe"] == 1.0
    assert parsed["q_charge"] == 0.0


def test_parse_fs_tax_breakdown_excludes_carrier_code_after_tot():
    """Carrier codes like DH350 appearing in operator notes after TOT must not
    be parsed as a tax code entry in the breakdown dict."""
    text = (
        "AUH EY DAC 350.00DBDO NUC350.00END ROE1.0\n"
        "FARE AED1285.00 EQU USD350.00 BD100 OB15\n"
        "YQ87 TAXES AED202 TOT AED1487\n"
        "OPERATED DH350 AUH-DAC\n"  # carrier DH flight 350 — must not be a tax
    )

    parsed = parse_fs_tax_breakdown(text)

    assert "DH" not in parsed["tax_breakdown"]
    assert parsed["yq_charge"] == 87.0
    assert parsed["total_taxes"] == 202.0


def test_parse_fs_tax_breakdown_excludes_aircraft_type_before_fare():
    """Aircraft type DH8 on a leg line appearing before the FARE keyword must
    not be captured as a tax code."""
    text = (
        "1  EY  456  DH8  AUH DAC\n"
        "FARE AED1285.00 EQU USD350.00 BD100\n"
        "YQ87 TAXES AED187 TOT AED1472\n"
    )

    parsed = parse_fs_tax_breakdown(text)

    assert "DH" not in parsed["tax_breakdown"]
    assert "BD" in parsed["tax_breakdown"]


def test_click_d_button_accepts_settled_tax_screen(monkeypatch):
    automation = SmartpointAutomation()
    sent_keys = []

    fs_text = """
PRICING OPTION 1
1   QR    639  N  09MAY DAC DOH   0305  0615
             Â«BOOKÂ»             +TQ                                                     D  R  +1
>
"""
    settled_tax_text = """
TOTAL JOURNEY TIME

DAC-DOH: 06:10

FS-1 ADT

REFUNDABLE: YES

PLATING CARRIER: QR QATAR AIRWAYS

DAC QR DOH Q20.00 935.00NJR4R1RI NUC955.00END ROE1.0

FARE USD955.00 EQU BDT117408 YQ0 TAXES BDT10156 TOT BDT127564
"""

    monkeypatch.setattr(automation, "focus", lambda force=False: True)
    monkeypatch.setattr(
        automation, "_text_line_to_pixel", lambda *args, **kwargs: (933, 237)
    )
    monkeypatch.setattr(
        automation, "_get_terminal_rect", lambda: type("Rect", (), {"width": lambda self: 716})()
    )
    monkeypatch.setattr(
        automation, "_wait_for_response", lambda *args, **kwargs: "INTERIM"
    )

    stable_reads = iter([settled_tax_text])
    monkeypatch.setattr(
        automation,
        "_wait_for_stable_screen",
        lambda *args, **kwargs: next(stable_reads),
    )

    monkeypatch.setattr(spa.pyautogui, "press", lambda *args, **kwargs: None)
    monkeypatch.setattr(spa.pyautogui, "moveTo", lambda *args, **kwargs: None)
    monkeypatch.setattr(spa.pyautogui, "click", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        spa.pyautogui,
        "typewrite",
        lambda text, interval=None: sent_keys.append(text),
    )

    result = automation.click_d_button(0, fs_text)

    assert "FARE USD955.00" in result
    assert "I" not in sent_keys


def test_click_d_button_anchors_to_selected_pricing_option_block(monkeypatch):
    automation = SmartpointAutomation()
    pixel_calls = []

    fs_text = "\n".join(
        [
            "HEADER WITH BOOK +TQ                                                     D  R",
            "PRICING OPTION 1",
            "1   BS    325  E  20MAY DAC CAN   2210  0350 #  WE   738",
            "             Ã‚Â«BOOKÃ‚Â»             +TQ                                                     D  R  +0",
            "PRICING OPTION 2",
            "1   QR    639  N  09MAY DAC DOH   0305  0615",
            "             Ã‚Â«BOOKÃ‚Â»             +TQ                                                     D  R  +0",
            ">",
        ]
    )
    settled_tax_text = """
TOTAL JOURNEY TIME
FS-2 ADT
REFUNDABLE: YES
FARE USD955.00 EQU BDT117408 YQ0 TAXES BDT10156 TOT BDT127564
"""

    def fake_text_line_to_pixel(text, line_idx, char_idx=None, x_ratio=0.5):
        pixel_calls.append((line_idx, char_idx, x_ratio))
        return (933, 200 + line_idx * 20)

    monkeypatch.setattr(automation, "focus", lambda force=False: True)
    monkeypatch.setattr(automation, "_text_line_to_pixel", fake_text_line_to_pixel)
    monkeypatch.setattr(
        automation, "_get_terminal_rect", lambda: type("Rect", (), {"width": lambda self: 716})()
    )
    monkeypatch.setattr(
        automation, "_wait_for_response", lambda *args, **kwargs: "INTERIM"
    )
    monkeypatch.setattr(
        automation,
        "_wait_for_stable_screen",
        lambda *args, **kwargs: settled_tax_text,
    )
    monkeypatch.setattr(spa.pyautogui, "press", lambda *args, **kwargs: None)
    monkeypatch.setattr(spa.pyautogui, "moveTo", lambda *args, **kwargs: None)
    monkeypatch.setattr(spa.pyautogui, "click", lambda *args, **kwargs: None)

    result = automation.click_d_button(1, fs_text)

    assert "FARE USD955.00" in result
    assert pixel_calls[0][0] == 6


def test_click_d_button_rejects_loose_keyword_screen_and_tries_next_offset(monkeypatch):
    automation = SmartpointAutomation()
    sent_keys = []
    move_calls = []

    fs_text = """
PRICING OPTION 1
1   QR    639  N  09MAY DAC DOH   0305  0615
             Â«BOOKÂ»             +TQ                                                     D  R  +1
>
"""
    bad_detail_text = """
FARE BASIS DETAILS
RULE TEXT
TAX MAY APPLY
"""
    settled_tax_text = """
TOTAL JOURNEY TIME
FS-1 ADT
REFUNDABLE: YES
FARE USD955.00 EQU BDT117408 YQ0 TAXES BDT10156 TOT BDT127564
"""
    response_texts = iter(["INTERIM_BAD", "RESET_PAGE", "INTERIM_GOOD"])
    settled_texts = iter([bad_detail_text, fs_text, settled_tax_text])

    monkeypatch.setattr(automation, "focus", lambda force=False: True)
    monkeypatch.setattr(
        automation, "_text_line_to_pixel", lambda *args, **kwargs: (933, 237)
    )
    monkeypatch.setattr(
        automation, "_get_terminal_rect", lambda: type("Rect", (), {"width": lambda self: 716})()
    )
    monkeypatch.setattr(
        automation, "_wait_for_response", lambda *args, **kwargs: next(response_texts)
    )
    monkeypatch.setattr(
        automation,
        "_wait_for_stable_screen",
        lambda *args, **kwargs: next(settled_texts),
    )

    monkeypatch.setattr(spa.pyautogui, "press", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        spa.pyautogui,
        "moveTo",
        lambda x, y, duration=None: move_calls.append((x, y)),
    )
    monkeypatch.setattr(spa.pyautogui, "click", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        spa.pyautogui,
        "typewrite",
        lambda text, interval=None: sent_keys.append(text),
    )

    result = automation.click_d_button(0, fs_text)

    assert "FARE USD955.00" in result
    assert "I" in sent_keys
    assert len(move_calls) >= 2


def test_click_d_button_keeps_trying_when_screen_returns_to_pricing_options(monkeypatch):
    automation = SmartpointAutomation()
    sent_keys = []
    move_calls = []

    fs_text = """
PRICING OPTION 1
1   BS    325  E  20MAY DAC CAN   2210  0350 #  WE   738      EBDCNO
             Â«BOOKÂ»             +TQ                                                     D  R  +0
>
"""
    repriced_text = """
>

TTL OF 1   PRICING OPTIONS AND 1     ITINERARY OPTIONS RETURNED

 PRICING OPTION 1                  TOTAL AMOUNT             28870 BDT
ADT
1   BS    325  E  20MAY DAC CAN   2210  0350 #  WE   738      EBDCNO
             Â«BOOKÂ»             +TQ                                                     D  R  +0
"""
    settled_tax_text = """
TOTAL JOURNEY TIME
FS-1 ADT
REFUNDABLE: YES
FARE USD955.00 EQU BDT117408 YQ0 TAXES BDT10156 TOT BDT127564
"""
    response_texts = iter(["INTERIM_BAD", "INTERIM_GOOD"])
    settled_texts = iter([repriced_text, settled_tax_text])

    monkeypatch.setattr(automation, "focus", lambda force=False: True)
    monkeypatch.setattr(
        automation, "_text_line_to_pixel", lambda *args, **kwargs: (933, 237)
    )
    monkeypatch.setattr(
        automation, "_get_terminal_rect", lambda: type("Rect", (), {"width": lambda self: 716})()
    )
    monkeypatch.setattr(
        automation, "_wait_for_response", lambda *args, **kwargs: next(response_texts)
    )
    monkeypatch.setattr(
        automation,
        "_wait_for_stable_screen",
        lambda *args, **kwargs: next(settled_texts),
    )

    monkeypatch.setattr(spa.pyautogui, "press", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        spa.pyautogui,
        "moveTo",
        lambda x, y, duration=None: move_calls.append((x, y)),
    )
    monkeypatch.setattr(spa.pyautogui, "click", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        spa.pyautogui,
        "typewrite",
        lambda text, interval=None: sent_keys.append(text),
    )

    result = automation.click_d_button(0, fs_text)

    assert "FARE USD955.00" in result
    assert "I" not in sent_keys
    assert len(move_calls) >= 2


def test_click_fare_amount_for_penalty_prefers_exact_unsaleable_line(monkeypatch):
    automation = SmartpointAutomation()
    page_text = "\n".join(
        [
            " 30 BG 500.00 YOW Y",
            " O30 BG 450.00 YOWU Y",
        ]
    )
    target_calls = []
    responses = iter(
        [
            "16. PENALTIES\nCHANGES",
            page_text,
        ]
    )

    monkeypatch.setattr(automation, "focus", lambda force=False: True)
    monkeypatch.setattr(
        automation,
        "_text_line_to_pixel",
        lambda text, line_idx, char_idx=None, x_ratio=0.5: (
            target_calls.append((line_idx, char_idx)) or (100, 200)
        ),
    )
    monkeypatch.setattr(
        automation, "_wait_for_response", lambda *args, **kwargs: next(responses)
    )
    monkeypatch.setattr(automation, "_copy_terminal_text", lambda: page_text)
    monkeypatch.setattr(spa.pyautogui, "moveTo", lambda *args, **kwargs: None)
    monkeypatch.setattr(spa.pyautogui, "click", lambda *args, **kwargs: None)
    monkeypatch.setattr(spa.pyautogui, "press", lambda *args, **kwargs: None)

    popup_text, restored_text = automation.click_fare_amount_for_penalty(
        page_text,
        {
            "line": 30,
            "line_token": "O30",
            "airline": "BG",
            "fare": 450.0,
            "fare_basis": "YOWU",
            "is_unsaleable": True,
            "raw_line": "O30 BG 450.00 YOWU Y",
        },
    )

    assert popup_text.startswith("16. PENALTIES")
    assert restored_text == page_text
    assert target_calls[0][0] == 1


def test_clipboard_adapter_prefers_native_win32_reader(monkeypatch):
    class FailingPyperclip:
        @staticmethod
        def paste():
            raise AssertionError("pyperclip fallback should not be used")

    monkeypatch.setattr(spa, "clipboard_paste", lambda: "CAPTURED TEXT")
    monkeypatch.setattr(spa, "_real_pyperclip", FailingPyperclip)

    assert spa.pyperclip.paste() == "CAPTURED TEXT"


def test_clipboard_adapter_falls_back_when_native_reader_is_empty(monkeypatch):
    class FakePyperclip:
        @staticmethod
        def paste():
            return "PYperclip fallback"

    monkeypatch.setattr(spa, "clipboard_paste", lambda: "")
    monkeypatch.setattr(spa, "_real_pyperclip", FakePyperclip)

    assert spa.pyperclip.paste() == "PYperclip fallback"


def test_copy_terminal_text_skips_hotkeys_when_window_not_foreground(monkeypatch):
    automation = SmartpointAutomation()

    class _Rect:
        left = 100
        top = 50

    class _Window:
        @staticmethod
        def rectangle():
            return _Rect()

    hotkey_calls = []

    automation.window = _Window()
    monkeypatch.setattr(automation, "focus", lambda force=False: True)
    monkeypatch.setattr(automation, "_is_window_foreground", lambda: False)
    monkeypatch.setattr(automation, "_safe_focus_click", lambda x, y: None)
    monkeypatch.setattr(spa.pyperclip, "copy", lambda text: None)
    monkeypatch.setattr(spa.pyperclip, "paste", lambda: "")
    monkeypatch.setattr(
        automation,
        "_send_clipboard_shortcuts",
        lambda: hotkey_calls.append(("copy",)),
    )
    monkeypatch.setattr(spa.time, "sleep", lambda *args, **kwargs: None)

    assert automation._copy_terminal_text() == ""
    assert hotkey_calls == []


def test_is_window_foreground_accepts_related_foreground_handle(monkeypatch):
    automation = SmartpointAutomation()

    class _Wrapper:
        handle = 100

    class _Window:
        @staticmethod
        def wrapper_object():
            return _Wrapper()

    class _User32:
        @staticmethod
        def GetForegroundWindow():
            return 200

        @staticmethod
        def GetAncestor(hwnd, flag):
            return {100: 100, 200: 100}.get(hwnd, hwnd)

        @staticmethod
        def IsChild(parent, child):
            return 0

        @staticmethod
        def GetWindowThreadProcessId(hwnd, pid_ref):
            pid_ref._obj.value = 1234
            return 1

    automation.window = _Window()
    monkeypatch.setattr(spa.ctypes, "windll", type("Windll", (), {"user32": _User32()})())

    assert automation._is_window_foreground() is True


def test_copy_terminal_text_uses_terminal_focus_point(monkeypatch):
    automation = SmartpointAutomation()
    clicks = []

    class _Window:
        pass

    automation.window = _Window()
    monkeypatch.setattr(automation, "focus", lambda force=False: True)
    monkeypatch.setattr(automation, "_get_terminal_focus_point", lambda: (444, 222))
    monkeypatch.setattr(automation, "_is_window_foreground", lambda: True)
    monkeypatch.setattr(
        automation, "_safe_focus_click", lambda x, y: clicks.append((x, y))
    )
    monkeypatch.setattr(spa.pyperclip, "copy", lambda text: None)
    monkeypatch.setattr(spa.pyperclip, "paste", lambda: "CAPTURED")
    monkeypatch.setattr(
        automation,
        "_send_clipboard_shortcuts",
        lambda: None,
    )
    monkeypatch.setattr(spa.pyautogui, "press", lambda *args, **kwargs: None)
    monkeypatch.setattr(spa.time, "sleep", lambda *args, **kwargs: None)

    assert automation._copy_terminal_text() == "CAPTURED"
    assert clicks[0] == (444, 222)


def test_wait_for_stable_screen_reuses_initial_text(monkeypatch):
    automation = SmartpointAutomation()
    reads = []

    monkeypatch.setattr(
        automation,
        "_copy_terminal_text",
        lambda: reads.append("copy") or "UNCHANGED",
    )
    monkeypatch.setattr(spa.time, "sleep", lambda *args, **kwargs: None)

    assert (
        automation._wait_for_stable_screen(
            initial_text="UNCHANGED", max_polls=2, interval=0.1
        )
        == "UNCHANGED"
    )
    assert reads == ["copy"]


def test_wait_for_response_raises_stop_requested(monkeypatch):
    stop_event = threading.Event()
    stop_event.set()
    automation = SmartpointAutomation(stop_event=stop_event)

    monkeypatch.setattr(spa.time, "sleep", lambda *args, **kwargs: None)

    try:
        automation._wait_for_response("BEFORE", timeout=0.5, poll_interval=0.1)
        assert False, "Expected StopRequested"
    except spa.StopRequested:
        pass


def test_clear_screen_raises_stop_requested(monkeypatch):
    stop_event = threading.Event()
    stop_event.set()
    automation = SmartpointAutomation(stop_event=stop_event)

    monkeypatch.setattr(automation, "focus", lambda force=False: True)

    try:
        automation.clear_screen()
        assert False, "Expected StopRequested"
    except spa.StopRequested:
        pass


def test_copy_terminal_text_stops_after_one_slower_retry(monkeypatch):
    automation = SmartpointAutomation()
    sent_shortcuts = []

    class _Window:
        pass

    pasted = iter(["", "CAPTURED"])
    automation.window = _Window()
    monkeypatch.setattr(automation, "focus", lambda force=False: True)
    monkeypatch.setattr(automation, "_get_terminal_focus_point", lambda: (444, 222))
    monkeypatch.setattr(automation, "_is_window_foreground", lambda: True)
    monkeypatch.setattr(automation, "_safe_focus_click", lambda x, y: None)
    monkeypatch.setattr(spa.pyperclip, "copy", lambda text: None)
    monkeypatch.setattr(spa.pyperclip, "paste", lambda: next(pasted))
    monkeypatch.setattr(
        automation,
        "_send_clipboard_shortcuts",
        lambda: sent_shortcuts.append("copy"),
    )
    monkeypatch.setattr(spa.pyautogui, "press", lambda *args, **kwargs: None)
    monkeypatch.setattr(spa.time, "sleep", lambda *args, **kwargs: None)

    assert automation._copy_terminal_text() == "CAPTURED"
    assert sent_shortcuts == ["copy", "copy"]


def test_copy_terminal_text_uses_heavy_fallback_after_two_empty_attempts(monkeypatch):
    automation = SmartpointAutomation()
    focus_calls = []
    sent_shortcuts = []
    clicks = []

    class _Window:
        pass

    pasted = iter(["", "", "CAPTURED"])
    automation.window = _Window()
    monkeypatch.setattr(
        automation, "focus", lambda force=False: focus_calls.append(force) or True
    )
    monkeypatch.setattr(automation, "_get_terminal_focus_point", lambda: (444, 222))
    monkeypatch.setattr(automation, "_is_window_foreground", lambda: True)
    monkeypatch.setattr(
        automation, "_safe_focus_click", lambda x, y: clicks.append((x, y))
    )
    monkeypatch.setattr(spa.pyperclip, "copy", lambda text: None)
    monkeypatch.setattr(spa.pyperclip, "paste", lambda: next(pasted))
    monkeypatch.setattr(
        automation,
        "_send_clipboard_shortcuts",
        lambda: sent_shortcuts.append("copy"),
    )
    monkeypatch.setattr(spa.pyautogui, "press", lambda *args, **kwargs: None)
    monkeypatch.setattr(spa.time, "sleep", lambda *args, **kwargs: None)

    assert automation._copy_terminal_text() == "CAPTURED"
    assert sent_shortcuts == ["copy", "copy", "copy"]
    assert len(focus_calls) == 2
    assert len(clicks) == 2


def test_copy_terminal_text_converts_keyboard_interrupt_to_runtime_error(monkeypatch):
    automation = SmartpointAutomation()

    class _Rect:
        left = 100
        top = 50

    class _Window:
        @staticmethod
        def rectangle():
            return _Rect()

    automation.window = _Window()
    monkeypatch.setattr(automation, "focus", lambda force=False: True)
    monkeypatch.setattr(automation, "_is_window_foreground", lambda: True)
    monkeypatch.setattr(automation, "_safe_focus_click", lambda x, y: None)
    monkeypatch.setattr(spa.pyperclip, "copy", lambda text: None)
    monkeypatch.setattr(spa.pyperclip, "paste", lambda: "")
    monkeypatch.setattr(
        automation,
        "_send_clipboard_shortcuts",
        lambda: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    monkeypatch.setattr(spa.time, "sleep", lambda *args, **kwargs: None)

    try:
        automation._copy_terminal_text()
        assert False, "Expected RuntimeError"
    except RuntimeError as exc:
        assert "Ctrl+C likely reached the console" in str(exc)


def test_get_terminal_focus_point_derives_missing_bounds_from_dimensions(monkeypatch):
    automation = SmartpointAutomation()

    class _Rect:
        left = 100
        top = 50

        @staticmethod
        def width():
            return 40

        @staticmethod
        def height():
            return 30

    monkeypatch.setattr(automation, "_get_terminal_rect", lambda: _Rect())

    assert automation._get_terminal_focus_point() == (150, 80)


def test_click_currency_link_retries_after_first_miss(monkeypatch):
    automation = SmartpointAutomation()
    moved = []
    fd_text = "HEADER\nBDT CURRENCY FARES EXISTS\nEND"
    loaded_text = "UPDATED SCREEN " + ("X" * 120)

    class _Rect:
        left = 100
        top = 50
        right = 500
        bottom = 250

        def width(self):
            return self.right - self.left

        def height(self):
            return self.bottom - self.top

    pasted = iter([fd_text, loaded_text])

    monkeypatch.setattr(automation, "focus", lambda force=False: True)
    monkeypatch.setattr(automation, "_get_terminal_rect", lambda: _Rect())
    monkeypatch.setattr(
        automation,
        "_wait_for_stable_screen",
        lambda initial_text=None, **kwargs: initial_text,
    )
    monkeypatch.setattr(automation, "_copy_terminal_text", lambda: next(pasted))
    monkeypatch.setattr(automation, "_has_dropdown_activated", lambda text: False)
    monkeypatch.setattr(
        automation,
        "_has_currency_redirect",
        lambda text: "CURRENCY FARES EXISTS" in text,
    )
    monkeypatch.setattr(
        spa.pyautogui,
        "moveTo",
        lambda x, y, duration=None: moved.append((x, y)),
    )
    monkeypatch.setattr(spa.pyautogui, "click", lambda *args, **kwargs: None)
    monkeypatch.setattr(spa.pyautogui, "press", lambda *args, **kwargs: None)
    monkeypatch.setattr(spa.time, "sleep", lambda *args, **kwargs: None)

    assert automation.click_currency_link(fd_text) == loaded_text
    assert len(moved) == 2


def test_send_clipboard_shortcuts_uses_pywinauto_send_keys(monkeypatch):
    automation = SmartpointAutomation()
    sent = []

    monkeypatch.setattr(spa._pw_kb, "send_keys", lambda keys: sent.append(keys))
    monkeypatch.setattr(spa.time, "sleep", lambda *args, **kwargs: None)

    automation._send_clipboard_shortcuts()

    assert sent == ["^a", "^c"]


def test_login_types_sign_on_username_and_password(monkeypatch):
    automation = SmartpointAutomation()
    sent_keys = []

    monkeypatch.setattr(automation, "focus", lambda force=False: True)
    monkeypatch.setattr(automation, "clear_screen", lambda: None)
    monkeypatch.setattr(
        automation,
        "_copy_terminal_text",
        lambda: "WELCOME TO SMARTPOINT",
    )
    monkeypatch.setattr(
        spa.pyautogui,
        "typewrite",
        lambda text, interval=None: sent_keys.append(text),
    )
    monkeypatch.setattr(spa.pyautogui, "press", lambda *args, **kwargs: None)
    monkeypatch.setattr(spa.time, "sleep", lambda *args, **kwargs: None)

    result = automation.login("user/name", "secret123", "3L5Q")

    assert result is True
    assert sent_keys == ["SON/Z3L5Q", "user/name", "secret123"]


# ── v1.5.15: D-click calibration reset + auto-invalidate ────────────────────────


def test_clear_d_click_offset_removes_saved_offset():
    cal = {"line_height": 20, "d_click_offset": [6, 12]}
    cleared = calibration.clear_d_click_offset(cal)
    assert "d_click_offset" not in cleared


def test_clear_d_click_offset_is_noop_when_none_saved():
    cal = {"line_height": 20}
    cleared = calibration.clear_d_click_offset(cal)
    assert "d_click_offset" not in cleared


def test_clear_d_click_offset_removes_both_anchored_variants():
    cal = {
        "line_height": 20,
        "d_click_offset": [49, 0],
        "d_click_char_x_offset": [0, 0],
    }
    cleared = calibration.clear_d_click_offset(cal)
    assert "d_click_offset" not in cleared
    assert "d_click_char_x_offset" not in cleared


def test_record_d_click_offset_stores_both_when_char_x_off_provided():
    cal = {"line_height": 20}
    updated = calibration.record_d_click_offset(cal, x_off=49, y_off=0, char_x_off=0)
    assert updated["d_click_offset"] == [49, 0]
    assert updated["d_click_char_x_offset"] == [0, 0]


def test_record_d_click_offset_keeps_legacy_only_when_char_x_off_none():
    cal = {"line_height": 20}
    updated = calibration.record_d_click_offset(cal, x_off=49, y_off=0, char_x_off=None)
    assert updated["d_click_offset"] == [49, 0]
    assert "d_click_char_x_offset" not in updated


def test_get_d_click_char_x_offset_returns_tuple():
    cal = {"d_click_char_x_offset": [0, 0]}
    assert calibration.get_d_click_char_x_offset(cal) == (0, 0)


def test_get_d_click_char_x_offset_returns_none_when_missing():
    cal = {"d_click_offset": [49, 0]}
    assert calibration.get_d_click_char_x_offset(cal) is None


def test_click_d_button_prefers_char_x_anchored_offset_when_present(monkeypatch):
    """v1.5.16: when d_click_char_x_offset is saved, click_d_button must
    target char_x + saved_char_x_off, NOT base_x + saved_x.  This is the
    point of anchoring to char_x — saved coords stay correct even when
    base_x shifts (terminal-width changes).
    """
    automation = SmartpointAutomation()
    move_calls: list[tuple[int, int]] = []

    # The saved char_x-anchored offset is (0, 0) — i.e. learned from a
    # click directly on the D glyph.  The legacy base_x offset (49, 0)
    # is also stored but should be IGNORED in favor of the char_x one.
    automation._cal = {
        "line_height": 20,
        "dpi": 96,
        "source": "dpi_auto",
        "click_deltas": [],
        "delta_correction": 0,
        "d_click_offset": [49, 0],
        "d_click_char_x_offset": [0, 0],
    }

    fs_text = "\n".join(
        [
            "PRICING OPTION 1",
            "1   EK    587  N  09MAY DAC DXB",
            "             \xabBOOK\xbb             +TQ                                                     D  R  +1",
            ">",
        ]
    )
    settled_tax_text = (
        "FS-1 ADT\n"
        "FARE USD955.00 EQU BDT117408 YQ0 TAXES BDT10156 TOT BDT127564\n"
    )

    # Simulate a different terminal width on this run vs when the offset
    # was learned: ratio_x=1740, char_x=1810. base_x = min(char_x-28,
    # ratio_x) = min(1782, 1740) = 1740. The legacy offset (49, 0) would
    # click at 1789 (left of D); the char_x offset (0, 0) maps to
    # base_x + (1810-1740) + 0 = 1810 (on D).
    pixel_returns = iter([(1740, 540), (1810, 540)])

    monkeypatch.setattr(automation, "focus", lambda force=False: True)
    monkeypatch.setattr(
        automation, "_text_line_to_pixel", lambda *a, **kw: next(pixel_returns)
    )
    monkeypatch.setattr(
        automation,
        "_get_terminal_rect",
        lambda: type("R", (), {"width": lambda self: 1500})(),
    )
    monkeypatch.setattr(automation, "_find_d_char_column", lambda line: 91)
    monkeypatch.setattr(automation, "_copy_terminal_text", lambda: "")

    call_counter = {"n": 0}

    def fake_resp(*a, **kw):
        call_counter["n"] += 1
        return fs_text

    def fake_stable(*a, **kw):
        if call_counter["n"] >= 1:
            return settled_tax_text
        return fs_text

    monkeypatch.setattr(automation, "_wait_for_response", fake_resp)
    monkeypatch.setattr(automation, "_wait_for_stable_screen", fake_stable)
    monkeypatch.setattr(calibration, "save_calibration", lambda *a, **kw: None)
    monkeypatch.setattr(spa.pyautogui, "press", lambda *a, **kw: None)
    monkeypatch.setattr(spa.pyautogui, "click", lambda *a, **kw: None)
    monkeypatch.setattr(spa.pyautogui, "typewrite", lambda *a, **kw: None)
    monkeypatch.setattr(spa.time, "sleep", lambda *a, **kw: None)
    monkeypatch.setattr(
        spa.pyautogui,
        "moveTo",
        lambda x, y, duration=None: move_calls.append((x, y)),
    )

    result = automation.click_d_button(0, fs_text)

    assert "FARE USD955.00" in result
    assert move_calls[0] == (1810, 540), (
        "char_x-anchored offset must place the first click on the actual D "
        f"glyph (x=1810), not on the legacy base_x position (x=1789).  Got: {move_calls[0]!r}"
    )


def test_click_d_button_falls_back_to_base_x_offset_when_char_x_anchored_missing(
    monkeypatch,
):
    """Legacy PCs that learned an offset under v1.5.14 or earlier have only
    d_click_offset, not d_click_char_x_offset.  The new code path must
    fall back gracefully to the base_x-relative offset."""
    automation = SmartpointAutomation()
    move_calls: list[tuple[int, int]] = []

    automation._cal = {
        "line_height": 20,
        "dpi": 96,
        "source": "dpi_auto",
        "click_deltas": [],
        "delta_correction": 0,
        "d_click_offset": [49, 0],
        # No d_click_char_x_offset (legacy install).
    }

    fs_text = "\n".join(
        [
            "PRICING OPTION 1",
            "1   EK    587  N",
            "             \xabBOOK\xbb             +TQ                                                     D  R  +1",
            ">",
        ]
    )
    settled_tax_text = (
        "FS-1 ADT\n"
        "FARE USD955.00 EQU BDT117408 YQ0 TAXES BDT10156 TOT BDT127564\n"
    )

    pixel_returns = iter([(1752, 540), (1801, 540)])

    monkeypatch.setattr(automation, "focus", lambda force=False: True)
    monkeypatch.setattr(
        automation, "_text_line_to_pixel", lambda *a, **kw: next(pixel_returns)
    )
    monkeypatch.setattr(
        automation,
        "_get_terminal_rect",
        lambda: type("R", (), {"width": lambda self: 1500})(),
    )
    monkeypatch.setattr(automation, "_find_d_char_column", lambda line: 91)
    monkeypatch.setattr(automation, "_copy_terminal_text", lambda: "")

    call_counter = {"n": 0}

    def fake_resp(*a, **kw):
        call_counter["n"] += 1
        return fs_text

    def fake_stable(*a, **kw):
        if call_counter["n"] >= 1:
            return settled_tax_text
        return fs_text

    monkeypatch.setattr(automation, "_wait_for_response", fake_resp)
    monkeypatch.setattr(automation, "_wait_for_stable_screen", fake_stable)
    monkeypatch.setattr(calibration, "save_calibration", lambda *a, **kw: None)
    monkeypatch.setattr(spa.pyautogui, "press", lambda *a, **kw: None)
    monkeypatch.setattr(spa.pyautogui, "click", lambda *a, **kw: None)
    monkeypatch.setattr(spa.pyautogui, "typewrite", lambda *a, **kw: None)
    monkeypatch.setattr(spa.time, "sleep", lambda *a, **kw: None)
    monkeypatch.setattr(
        spa.pyautogui,
        "moveTo",
        lambda x, y, duration=None: move_calls.append((x, y)),
    )

    automation.click_d_button(0, fs_text)

    # Falls back to base_x + saved_x = 1752 + 49 = 1801.
    assert move_calls[0] == (1801, 540), (
        f"Legacy fallback must use base_x + saved_x.  Got: {move_calls[0]!r}"
    )


def test_click_d_button_clears_stale_saved_offset_after_fanout_exhausts(monkeypatch):
    """v1.5.15: when every auto-click attempt fails AND a saved offset was
    in play, the offset is auto-invalidated so the next run starts fresh
    with the 5-second manual learning window.  This unblocks PCs whose
    saved offset has gone stale (e.g. terminal width changed since
    learning) without ever changing click order on PCs where it works."""
    automation = SmartpointAutomation()

    automation._cal = {
        "line_height": 20,
        "dpi": 96,
        "source": "dpi_auto",
        "click_deltas": [],
        "delta_correction": 0,
        "d_click_offset": [6, 12],
    }
    automation._stop = threading.Event()
    automation._stop.set()

    fs_text = "\n".join(
        [
            "PRICING OPTION 1",
            "1   EK    587  N  09MAY DAC DXB",
            "             \xabBOOK\xbb             +TQ                                                     D  R  +1",
            ">",
        ]
    )

    monkeypatch.setattr(automation, "focus", lambda force=False: True)
    monkeypatch.setattr(automation, "_text_line_to_pixel", lambda *a, **kw: (1752, 540))
    monkeypatch.setattr(
        automation,
        "_get_terminal_rect",
        lambda: type("R", (), {"width": lambda self: 1500})(),
    )
    monkeypatch.setattr(automation, "_find_d_char_column", lambda line: 91)
    monkeypatch.setattr(automation, "_wait_for_response", lambda *a, **kw: fs_text)
    monkeypatch.setattr(automation, "_wait_for_stable_screen", lambda *a, **kw: fs_text)
    monkeypatch.setattr(automation, "_copy_terminal_text", lambda: "")

    saved_calls: list[dict] = []
    monkeypatch.setattr(
        calibration, "save_calibration", lambda cal: saved_calls.append(dict(cal))
    )
    monkeypatch.setattr(spa.pyautogui, "press", lambda *a, **kw: None)
    monkeypatch.setattr(spa.pyautogui, "click", lambda *a, **kw: None)
    monkeypatch.setattr(spa.pyautogui, "moveTo", lambda *a, **kw: None)
    monkeypatch.setattr(spa.pyautogui, "typewrite", lambda *a, **kw: None)
    monkeypatch.setattr(spa.time, "sleep", lambda *a, **kw: None)

    result = automation.click_d_button(0, fs_text)

    assert result == ""
    assert saved_calls, "Expected save_calibration to be called for invalidation"
    assert "d_click_offset" not in saved_calls[-1], (
        f"Saved offset must be cleared after fan-out exhausts, got: {saved_calls[-1]!r}"
    )
    assert "d_click_offset" not in automation._cal


def test_click_d_button_does_not_clear_offset_when_none_was_saved(monkeypatch):
    """No saved offset = nothing stale to invalidate. save_calibration must
    not be called for that purpose."""
    automation = SmartpointAutomation()
    automation._cal = {
        "line_height": 20,
        "dpi": 96,
        "source": "dpi_auto",
        "click_deltas": [],
        "delta_correction": 0,
    }
    automation._stop = threading.Event()
    automation._stop.set()

    fs_text = "\n".join(
        [
            "PRICING OPTION 1",
            "1   EK    587  N",
            "             \xabBOOK\xbb             +TQ                                                     D  R  +1",
            ">",
        ]
    )

    monkeypatch.setattr(automation, "focus", lambda force=False: True)
    monkeypatch.setattr(automation, "_text_line_to_pixel", lambda *a, **kw: (1752, 540))
    monkeypatch.setattr(
        automation,
        "_get_terminal_rect",
        lambda: type("R", (), {"width": lambda self: 1500})(),
    )
    monkeypatch.setattr(automation, "_find_d_char_column", lambda line: 91)
    monkeypatch.setattr(automation, "_wait_for_response", lambda *a, **kw: fs_text)
    monkeypatch.setattr(automation, "_wait_for_stable_screen", lambda *a, **kw: fs_text)
    monkeypatch.setattr(automation, "_copy_terminal_text", lambda: "")

    saved_calls: list[dict] = []
    monkeypatch.setattr(
        calibration, "save_calibration", lambda cal: saved_calls.append(dict(cal))
    )
    monkeypatch.setattr(spa.pyautogui, "press", lambda *a, **kw: None)
    monkeypatch.setattr(spa.pyautogui, "click", lambda *a, **kw: None)
    monkeypatch.setattr(spa.pyautogui, "moveTo", lambda *a, **kw: None)
    monkeypatch.setattr(spa.pyautogui, "typewrite", lambda *a, **kw: None)
    monkeypatch.setattr(spa.time, "sleep", lambda *a, **kw: None)

    automation.click_d_button(0, fs_text)

    assert saved_calls == [], (
        "save_calibration must NOT be called when there was no saved offset"
    )


# ── v1.5.17: manual-click region validation + saved-offset sanity + FS-N ──────


def _stub_rect(left=1147, top=93, right=1854, bottom=1013):
    return type(
        "Rect",
        (),
        {
            "left": left,
            "top": top,
            "right": right,
            "bottom": bottom,
            "width": lambda self: right - left,
            "height": lambda self: bottom - top,
        },
    )()


def test_is_manual_click_in_d_region_accepts_click_on_d_row(monkeypatch):
    automation = SmartpointAutomation()
    monkeypatch.setattr(automation, "_get_terminal_rect", lambda: _stub_rect())
    # base_x=1751 (real D column on USBA-27784), base_y=508 (target row).
    # Click at (1759, 520) is on the actual D glyph — must accept.
    assert automation._is_manual_click_in_d_region(1759, 520, 1751, 508)


def test_is_manual_click_in_d_region_rejects_tab_strip_click(monkeypatch):
    """The exact (1197, 123) bogus learn from the work-PC log must be rejected.
    That coordinate is inside the SmartRichTextBox rect but ~554 px left of
    base_x and ~385 px above base_y — clearly a stray (focus recovery,
    tab-strip click) and not a D click."""
    automation = SmartpointAutomation()
    monkeypatch.setattr(automation, "_get_terminal_rect", lambda: _stub_rect())
    assert not automation._is_manual_click_in_d_region(1197, 123, 1751, 508)


def test_is_manual_click_in_d_region_rejects_book_column_click(monkeypatch):
    """BOOK on this layout sits ~500 px left of base_x; a click there should
    not be attributed as a D learn."""
    automation = SmartpointAutomation()
    monkeypatch.setattr(automation, "_get_terminal_rect", lambda: _stub_rect())
    assert not automation._is_manual_click_in_d_region(1234, 508, 1751, 508)


def test_is_manual_click_in_d_region_rejects_outside_terminal_pane(monkeypatch):
    automation = SmartpointAutomation()
    monkeypatch.setattr(automation, "_get_terminal_rect", lambda: _stub_rect())
    # Just left of L=1147.
    assert not automation._is_manual_click_in_d_region(1146, 508, 1751, 508)
    # Just below B=1013.
    assert not automation._is_manual_click_in_d_region(1759, 1014, 1751, 508)


def test_saved_offset_is_sane_accepts_typical_offset():
    # The (8, 9) offset learned on USBA-27784 is well within sane bounds for
    # a 707-px-wide pane with line_height=20.
    assert SmartpointAutomation._saved_offset_is_sane(8, 9, 707, 20) is True


def test_saved_offset_is_sane_rejects_bogus_offset_from_log():
    """The (-554, -385) offset that was bogusly learned at 09:50:43 on the
    work PC must be rejected by sanity check — pane width is 707, so |x|
    must be <= 353."""
    assert SmartpointAutomation._saved_offset_is_sane(-554, -385, 707, 20) is False


def test_saved_offset_is_sane_rejects_excessive_y():
    # 4 * line_height = 80. y=120 exceeds.
    assert SmartpointAutomation._saved_offset_is_sane(8, 120, 707, 20) is False


def test_post_click_screen_matches_option_accepts_correct_fs_n():
    text = "TOTAL JOURNEY TIME\nFS-3 ADT\nREFUNDABLE: YES\nFARE USD955.00 EQU BDT117408 YQ0 TAXES BDT10156 TOT BDT127564"
    # option_index=2 → expects FS-3 ADT, present.
    assert SmartpointAutomation._post_click_screen_matches_option(text, 2) is True


def test_post_click_screen_matches_option_rejects_wrong_fs_n():
    """The +TQ-vs-D confusion on the work PC: pyautogui clicked +TQ, the
    screen looked tax-breakdown-shaped, but it showed FS-1 ADT (not FS-3
    for option 3). Must reject so we don't save a +TQ offset."""
    text = "TOTAL JOURNEY TIME\nFS-1 ADT\nREFUNDABLE: YES\nFARE USD955.00 EQU BDT117408 YQ0 TAXES BDT10156 TOT BDT127564"
    assert SmartpointAutomation._post_click_screen_matches_option(text, 2) is False


def test_post_click_screen_matches_option_rejects_non_tax_breakdown():
    text = "PRICING OPTION 1\nADT\n1 BG 327 D 30MAY DAC AUH"
    assert SmartpointAutomation._post_click_screen_matches_option(text, 0) is False


def test_click_d_button_clears_bogus_saved_offset_on_load(monkeypatch):
    """Integration: when calibration.json has a wildly out-of-pane offset
    (e.g. the (-554, -385) bogus learn from the work-PC log), click_d_button
    must clear it on entry rather than replaying off-screen clicks."""
    automation = SmartpointAutomation()
    automation._cal = {
        "line_height": 20,
        "dpi": 96,
        "source": "dpi_auto",
        "click_deltas": [],
        "delta_correction": 0,
        "d_click_offset": [-554, -385],
        "d_click_char_x_offset": [-603, -385],
    }
    automation._stop = threading.Event()
    automation._stop.set()

    fs_text = "\n".join(
        [
            "PRICING OPTION 1",
            "1   BS    321  V  30MAY DAC MCT",
            "             \xabBOOK\xbb             +TQ                                                     D  R  +0",
            ">",
        ]
    )

    monkeypatch.setattr(automation, "focus", lambda force=False: True)
    monkeypatch.setattr(automation, "_text_line_to_pixel", lambda *a, **kw: (1751, 268))
    monkeypatch.setattr(automation, "_get_terminal_rect", lambda: _stub_rect())
    monkeypatch.setattr(automation, "_find_d_char_column", lambda line: 91)
    monkeypatch.setattr(automation, "_wait_for_response", lambda *a, **kw: fs_text)
    monkeypatch.setattr(automation, "_wait_for_stable_screen", lambda *a, **kw: fs_text)
    monkeypatch.setattr(automation, "_copy_terminal_text", lambda: "")

    saved_calls: list[dict] = []
    monkeypatch.setattr(
        calibration, "save_calibration", lambda cal: saved_calls.append(dict(cal))
    )
    monkeypatch.setattr(spa.pyautogui, "press", lambda *a, **kw: None)
    monkeypatch.setattr(spa.pyautogui, "click", lambda *a, **kw: None)
    monkeypatch.setattr(spa.pyautogui, "moveTo", lambda *a, **kw: None)
    monkeypatch.setattr(spa.pyautogui, "typewrite", lambda *a, **kw: None)
    monkeypatch.setattr(spa.time, "sleep", lambda *a, **kw: None)

    automation.click_d_button(0, fs_text)

    # The bogus saved offset must have been cleared on entry.
    assert saved_calls, "Expected save_calibration to be called for the clear"
    assert "d_click_offset" not in saved_calls[0], (
        f"Saved offset must be cleared on load when out of sane bounds: {saved_calls[0]!r}"
    )
    assert "d_click_offset" not in automation._cal


def test_click_d_button_ignores_stray_manual_click_during_initial_window(
    monkeypatch,
):
    """Integration: with no saved offset, the 5-second manual window opens.
    A click captured at (1197, 123) (the bogus stray from the work-PC log)
    must be ignored, not learned."""
    automation = SmartpointAutomation()
    automation._cal = {
        "line_height": 20,
        "dpi": 96,
        "source": "dpi_auto",
        "click_deltas": [],
        "delta_correction": 0,
    }
    automation._stop = threading.Event()
    automation._stop.set()  # Stops the manual window quickly.

    fs_text = "\n".join(
        [
            "PRICING OPTION 1",
            "1   BS    321  V  30MAY DAC MCT",
            "             \xabBOOK\xbb             +TQ                                                     D  R  +0",
            ">",
        ]
    )

    monkeypatch.setattr(automation, "focus", lambda force=False: True)
    monkeypatch.setattr(automation, "_text_line_to_pixel", lambda *a, **kw: (1751, 268))
    monkeypatch.setattr(automation, "_get_terminal_rect", lambda: _stub_rect())
    monkeypatch.setattr(automation, "_find_d_char_column", lambda line: 91)
    monkeypatch.setattr(automation, "_wait_for_response", lambda *a, **kw: fs_text)
    monkeypatch.setattr(automation, "_wait_for_stable_screen", lambda *a, **kw: fs_text)
    monkeypatch.setattr(automation, "_copy_terminal_text", lambda: "")

    saved_calls: list[dict] = []
    monkeypatch.setattr(
        calibration, "save_calibration", lambda cal: saved_calls.append(dict(cal))
    )
    monkeypatch.setattr(spa.pyautogui, "press", lambda *a, **kw: None)
    monkeypatch.setattr(spa.pyautogui, "click", lambda *a, **kw: None)
    monkeypatch.setattr(spa.pyautogui, "moveTo", lambda *a, **kw: None)
    monkeypatch.setattr(spa.pyautogui, "typewrite", lambda *a, **kw: None)
    monkeypatch.setattr(spa.time, "sleep", lambda *a, **kw: None)

    automation.click_d_button(0, fs_text)

    # Even if a stray click had been recorded, no learn should happen.
    assert "d_click_offset" not in automation._cal, (
        "A stray click outside the D-row region must not be learned"
    )
