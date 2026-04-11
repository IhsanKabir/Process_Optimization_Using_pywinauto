import smartpoint_automation as spa
from smartpoint_automation import SmartpointAutomation
from tax_breakdown_parser import (
    looks_like_fs_tax_breakdown,
    parse_fs_tax_breakdown,
)


def test_has_more_prompt_ignores_end_signal():
    automation = SmartpointAutomation()

    text = "PAGE 1\n\u00abMore Flights\u00bb\nEND\n>"

    assert automation._has_end_signal(text) is True
    assert automation._has_more_prompt(text) is False


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
