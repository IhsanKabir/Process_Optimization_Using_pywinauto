"""Pure helpers behind the GUI: route/airline choices, filter checks,
re-run pairs and exact airline+route selection."""

import pytest
from openpyxl import Workbook

from exceptions import ValidationError
from gui_support import (
    configured_choices,
    filter_problems,
    find_latest_rerun_report,
    pairs_to_text,
    rerun_pairs_from_report,
)
from route_filters import parse_route_pairs, select_pair_commands


def _cmd(airline, origin, dest):
    return {
        "origin": origin,
        "destination": dest,
        "airline": airline,
        "route": f"{origin}-{dest}",
        "command": f"FD{origin}{dest}/{airline}",
    }


COMMANDS = [
    _cmd("EK", "DAC", "DXB"),
    _cmd("BG", "BKK", "DAC"),
    _cmd("BS", "DAC", "BKK"),
    _cmd("BS", "BKK", "DAC"),
    _cmd("FZ", "DXB", "DAC"),
    _cmd("BG", "DAC", "BKK"),
]


# ── choices ─────────────────────────────────────────────────────────────────


def test_configured_choices_order_routes_and_airlines():
    routes, airlines = configured_choices(COMMANDS)

    assert airlines == ["BS", "BG", "EK", "FZ"]
    # Outbound from DAC first, then its return, per destination.
    assert routes == ["DAC-BKK", "BKK-DAC", "DAC-DXB", "DXB-DAC"]


# ── filter checks ───────────────────────────────────────────────────────────


def test_filter_problems_accepts_valid_and_blank():
    assert filter_problems("DAC-BKK, DAC-DXB", "BS,bg") == []
    assert filter_problems("", "") == []


def test_filter_problems_names_each_bad_entry():
    problems = filter_problems("DAC-BKK,DACBK", "BS,B")

    assert len(problems) == 2
    assert "DACBK" in problems[0]
    assert "B" in problems[1]


# ── re-run pairs ────────────────────────────────────────────────────────────


def _report_with_rerun(path, rows):
    wb = Workbook()
    wb.active.title = "Side-by-Side Comparison"
    ws = wb.create_sheet("Re-run Needed")
    ws.cell(row=4, column=1, value="Airline")
    ws.cell(row=4, column=2, value="Route")
    ws.cell(row=4, column=4, value="Missing")
    for r, (airline, route, missing) in enumerate(rows, 5):
        ws.cell(row=r, column=1, value=airline)
        ws.cell(row=r, column=2, value=route)
        ws.cell(row=r, column=4, value=missing)
    wb.save(path)


def test_rerun_pairs_from_report(tmp_path):
    path = tmp_path / "fare_report_2026-10-07_1230.xlsx"
    _report_with_rerun(
        path,
        [("BS", "DOH-ZYL", "return route not extracted"), ("TG", "BKK-DAC", "FD THB")],
    )

    pairs = rerun_pairs_from_report(str(path))

    assert [(p["airline"], p["route"]) for p in pairs] == [
        ("BS", "DOH-ZYL"),
        ("TG", "BKK-DAC"),
    ]
    assert pairs_to_text(pairs) == "BS:DOH-ZYL,TG:BKK-DAC"


def test_rerun_pairs_empty_when_report_has_no_rerun_sheet(tmp_path):
    path = tmp_path / "fare_report_clean.xlsx"
    Workbook().save(path)

    assert rerun_pairs_from_report(str(path)) == []


def test_find_latest_rerun_report_skips_clean_and_partial_reports(tmp_path):
    import os
    import time

    older = tmp_path / "fare_report_2026-10-07_1000.xlsx"
    _report_with_rerun(older, [("BS", "DAC-BKK", "no tax breakdown")])
    clean = tmp_path / "fare_report_2026-10-07_1100.xlsx"
    Workbook().save(clean)
    now = time.time()
    os.utime(older, (now - 100, now - 100))
    os.utime(clean, (now, now))

    # The newest report is clean, so nothing needs re-running.
    assert find_latest_rerun_report(str(tmp_path)) is None

    os.utime(older, (now + 10, now + 10))
    assert find_latest_rerun_report(str(tmp_path)) == str(older)


# ── exact airline+route pairs (main --pairs) ────────────────────────────────


def test_parse_route_pairs_validates_and_normalises():
    assert parse_route_pairs(" bs:dac-bkk , FZ:DXBDAC ") == [
        ("BS", "DAC", "BKK"),
        ("FZ", "DXB", "DAC"),
    ]
    with pytest.raises(ValidationError):
        parse_route_pairs("BS-DAC-BKK")


def test_select_pair_commands_keeps_exact_pairs_and_generates_missing():
    pairs = [("BS", "DAC", "BKK"), ("TG", "BKK", "DAC")]

    selected = select_pair_commands(COMMANDS, pairs)

    assert [c["command"] for c in selected] == ["FDDACBKK/BS", "FDBKKDAC/TG"]
    assert selected[1]["route"] == "BKK-DAC"


# ── resume ──────────────────────────────────────────────────────────────────


def test_resumable_run_needs_unfinished_run_with_checkpoint(tmp_path):
    import json

    from gui_support import resumable_run

    cp = tmp_path / "checkpoint_2026-10-07_1200.json"
    cp.write_text(json.dumps({"completed_commands": ["FDDACBKK/BS"]}))
    run = {
        "session": "2026-10-07_1200",
        "finished": False,
        "settings": {"mode": "fare"},
    }

    found = resumable_run(run, str(tmp_path))
    assert found == {"path": str(cp), "completed": 1, "settings": {"mode": "fare"}}

    assert resumable_run(dict(run, finished=True), str(tmp_path)) is None
    assert resumable_run(dict(run, session="missing"), str(tmp_path)) is None
    assert resumable_run(None, str(tmp_path)) is None
    cp.write_text(json.dumps({"completed_commands": []}))
    assert resumable_run(run, str(tmp_path)) is None
