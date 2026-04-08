from openpyxl import Workbook

from excel_report import (
    _format_rbd_label,
    _group_rbds_by_cabin_break,
    _write_individual_tables_sheet,
    _write_section,
)

RBD_SORT_ORDER = [
    "F",
    "A",
    "J",
    "C",
    "D",
    "I",
    "Z",
    "Y",
    "B",
    "M",
    "H",
    "K",
    "Q",
    "T",
    "N",
    "R",
    "V",
    "X",
    "L",
    "U",
    "E",
    "G",
    "S",
    "W",
    "O",
]


def test_group_rbds_by_cabin_break_for_bg():
    premium_rbds, economy_rbds = _group_rbds_by_cabin_break(
        {"Y", "W", "J"},
        ["BG"],
        RBD_SORT_ORDER,
    )

    assert premium_rbds == ["J", "W"]
    assert economy_rbds == ["Y"]


def test_group_rbds_by_cabin_break_defaults_unknown_to_economy():
    premium_rbds, economy_rbds = _group_rbds_by_cabin_break(
        {"J", "Y"},
        ["OV"],
        RBD_SORT_ORDER,
    )

    assert premium_rbds == ["J"]
    assert economy_rbds == ["Y"]


def test_group_rbds_by_cabin_break_respects_premium_business():
    premium_rbds, economy_rbds = _group_rbds_by_cabin_break(
        {"Y", "W", "U", "J"},
        ["MU"],
        RBD_SORT_ORDER,
    )

    assert premium_rbds == ["U", "J", "W"]
    assert economy_rbds == ["Y"]


def test_group_rbds_by_cabin_break_handles_all_economy_airlines():
    premium_rbds, economy_rbds = _group_rbds_by_cabin_break(
        {"M", "A", "Y"},
        ["QP"],
        RBD_SORT_ORDER,
    )

    assert premium_rbds == []
    assert economy_rbds == ["M", "A", "Y"]


def test_format_rbd_label_avoids_duplicate_unsaleable_suffix():
    assert _format_rbd_label("Y (Unsaleable)", True) == "Y (Unsaleable)"


def test_write_section_inserts_gap_before_economy_rows():
    wb = Workbook()
    ws = wb.active

    entries = [
        (
            "BG",
            "DAC",
            "BG_DAC-MLE",
            {
                "currency": "USD",
                "rbd_data": {
                    "J": {"ow_fare": 300},
                    "W": {"ow_fare": 200},
                    "Y": {"ow_fare": 100},
                },
            },
        )
    ]

    _write_section(
        ws,
        1,
        "MLE",
        "outbound",
        entries,
        {"BG": "Biman Bangladesh"},
        {"DAC": "Dhaka", "MLE": "Male"},
        ["DAC"],
        RBD_SORT_ORDER,
        None,
    )

    assert ws.cell(row=3, column=1).value == "J"
    assert ws.cell(row=4, column=1).value == "W"
    assert ws.cell(row=5, column=1).value is None
    assert ws.cell(row=6, column=1).value == "Y"


def test_write_individual_tables_sheet_inserts_gap_before_economy_rows():
    wb = Workbook()
    ws = wb.active

    all_route_data = {
        "BG_DAC-MLE": {
            "currency": "USD",
            "fs_taxes": {},
            "rbd_data": {
                "J": {"ow_fare": 300},
                "W": {"ow_fare": 200},
                "Y": {"ow_fare": 100},
            },
        }
    }
    sections = {
        ("MLE", "outbound"): [("BG", "DAC", "BG_DAC-MLE", all_route_data["BG_DAC-MLE"])]
    }

    _write_individual_tables_sheet(
        ws,
        all_route_data,
        sections,
        {"BG": "Biman Bangladesh"},
        {"DAC": "Dhaka", "MLE": "Male"},
        RBD_SORT_ORDER,
        ["DAC"],
        None,
    )

    assert ws.cell(row=8, column=1).value == "J"
    assert ws.cell(row=9, column=1).value == "W"
    assert ws.cell(row=10, column=1).value is None
    assert ws.cell(row=11, column=1).value == "Y"
