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
    long_text = "\n".join(["ROW"] * 30 + ["          More Flights"])
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


def test_click_d_button_accepts_settled_tax_screen(monkeypatch):
    automation = SmartpointAutomation()
    sent_keys = []

    fs_text = """
PRICING OPTION 1
1   QR    639  N  09MAY DAC DOH   0305  0615
             «BOOK»             +TQ                                                     D  R  +1
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
            "             Â«BOOKÂ»             +TQ                                                     D  R  +0",
            "PRICING OPTION 2",
            "1   QR    639  N  09MAY DAC DOH   0305  0615",
            "             Â«BOOKÂ»             +TQ                                                     D  R  +0",
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
             «BOOK»             +TQ                                                     D  R  +1
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
             «BOOK»             +TQ                                                     D  R  +0
>
"""
    repriced_text = """
>

TTL OF 1   PRICING OPTIONS AND 1     ITINERARY OPTIONS RETURNED

 PRICING OPTION 1                  TOTAL AMOUNT             28870 BDT
ADT
1   BS    325  E  20MAY DAC CAN   2210  0350 #  WE   738      EBDCNO
             «BOOK»             +TQ                                                     D  R  +0
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
