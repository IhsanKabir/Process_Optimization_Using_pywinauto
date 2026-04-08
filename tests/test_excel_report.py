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
    upper_rbds, economy_rbds = _group_rbds_by_cabin_break(
        {"Y", "W", "J"},
        ["BG"],
        RBD_SORT_ORDER,
    )

    assert upper_rbds == ["J"]
    assert economy_rbds == ["Y", "W"]


def test_group_rbds_by_cabin_break_defaults_unknown_to_economy():
    upper_rbds, economy_rbds = _group_rbds_by_cabin_break(
        {"J", "Y"},
        ["OV"],
        RBD_SORT_ORDER,
    )

    assert upper_rbds == ["J"]
    assert economy_rbds == ["Y"]


def test_group_rbds_by_cabin_break_respects_premium_business():
    upper_rbds, economy_rbds = _group_rbds_by_cabin_break(
        {"Y", "W", "U", "J"},
        ["MU"],
        RBD_SORT_ORDER,
    )

    assert upper_rbds == ["J", "U"]
    assert economy_rbds == ["Y", "W"]


def test_group_rbds_by_cabin_break_handles_all_economy_airlines():
    upper_rbds, economy_rbds = _group_rbds_by_cabin_break(
        {"M", "A", "Y"},
        ["QP"],
        RBD_SORT_ORDER,
    )

    assert upper_rbds == []
    assert economy_rbds == ["A", "Y", "M"]


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
                    "Y": {"ow_fare": 250},
                    "W": {"ow_fare": 200},
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
    assert ws.cell(row=4, column=1).value is None
    assert ws.cell(row=5, column=1).value == "Y"
    assert ws.cell(row=6, column=1).value == "W"


def test_write_section_places_unsaleable_rows_last():
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
                    "Y": {"ow_fare": 250},
                    "W": {"ow_fare": 200},
                    "B": {
                        "ow_fare": 150,
                        "ow_fare_basis": "BOW (Unsaleable)",
                    },
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
    assert ws.cell(row=4, column=1).value is None
    assert ws.cell(row=5, column=1).value == "Y"
    assert ws.cell(row=6, column=1).value == "W"
    assert ws.cell(row=7, column=1).value == "B (Unsaleable)"


def test_write_section_sorts_economy_by_highest_fare():
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
                    "Y": {"ow_fare": 180},
                    "W": {"ow_fare": 210},
                    "B": {"ow_fare": 150},
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

    assert ws.cell(row=3, column=1).value == "W"
    assert ws.cell(row=4, column=1).value == "Y"
    assert ws.cell(row=5, column=1).value == "B"


def test_write_individual_tables_sheet_inserts_gap_before_economy_rows():
    wb = Workbook()
    ws = wb.active

    all_route_data = {
        "BG_DAC-MLE": {
            "currency": "USD",
            "fs_taxes": {},
            "rbd_data": {
                "J": {"ow_fare": 300},
                "Y": {"ow_fare": 250},
                "W": {"ow_fare": 200},
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
    assert ws.cell(row=9, column=1).value is None
    assert ws.cell(row=10, column=1).value == "Y"
    assert ws.cell(row=11, column=1).value == "W"


def test_write_individual_tables_sheet_keeps_only_fd_columns_without_tax_data():
    wb = Workbook()
    ws = wb.active

    all_route_data = {
        "BG_DAC-MLE": {
            "currency": "USD",
            "fs_taxes": {},
            "rbd_data": {
                "J": {"ow_fare": 300, "rt_fare": 500},
                "Y": {"ow_fare": 200, "rt_fare": 350},
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

    assert ws.cell(row=7, column=1).value == "RBD"
    assert ws.cell(row=7, column=2).value == "OW/USD"
    assert ws.cell(row=7, column=3).value == "RT/USD"
    assert ws.cell(row=7, column=4).value is None


def test_write_individual_tables_sheet_keeps_tax_columns_when_tax_data_present():
    wb = Workbook()
    ws = wb.active

    all_route_data = {
        "BG_DAC-MLE": {
            "currency": "USD",
            "fs_taxes": {
                "total_taxes": 5000,
                "yq_charge": 1200,
                "exchange_rate": 120,
            },
            "rbd_data": {
                "J": {"ow_fare": 300, "rt_fare": 500},
                "Y": {"ow_fare": 200, "rt_fare": 350},
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

    assert ws.cell(row=7, column=1).value == "RBD"
    assert ws.cell(row=7, column=2).value == "OW/USD"
    assert ws.cell(row=7, column=3).value == "With YQ/OW(USD)"
    assert ws.cell(row=7, column=4).value == "OW/Gross(BDT)"
    assert ws.cell(row=7, column=5).value == "RT/USD"
    assert ws.cell(row=7, column=6).value == "With YQ/RT(USD)"
    assert ws.cell(row=7, column=7).value == "RT/Gross(BDT)"
