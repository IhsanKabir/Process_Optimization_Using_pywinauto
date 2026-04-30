from openpyxl import Workbook

from excel_report import (
    _format_rbd_label,
    _group_rbds_by_cabin_break,
    _write_individual_tables_sheet,
    _write_section,
    _write_tax_breakdown_sheet,
    _write_yq_charges_sheet,
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


def test_write_section_keeps_unsaleable_suffix_when_rbd_key_is_tagged():
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
                    "Y": {"ow_fare": 250},
                    "B (Unsaleable)": {
                        "ow_fare": 150,
                        "ow_fare_basis": "BOW",
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

    assert ws.cell(row=3, column=1).value == "Y"
    assert ws.cell(row=4, column=1).value == "B (Unsaleable)"


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

    # v1.5.18: DAC-origin routes (BG_DAC-MLE here) keep gross in BDT —
    # local currency of the booking office.  Non-DAC origins use the
    # fare's base currency (covered by a separate test below).
    assert ws.cell(row=7, column=1).value == "RBD"
    assert ws.cell(row=7, column=2).value == "OW/USD"
    assert ws.cell(row=7, column=3).value == "With YQ/OW(USD)"
    assert ws.cell(row=7, column=4).value == "OW/Gross(BDT)"
    assert ws.cell(row=7, column=5).value == "RT/USD"
    assert ws.cell(row=7, column=6).value == "With YQ/RT(USD)"
    assert ws.cell(row=7, column=7).value == "RT/Gross(BDT)"


def test_individual_tables_sheet_uses_base_currency_for_non_dac_origin():
    """v1.5.18 rule: gross fare for routes whose outbound origin is NOT
    DAC stays in the fare's base currency (e.g. CAN-DAC on a CNY-base
    fare → ``OW/Gross(CNY)``)."""
    wb = Workbook()
    ws = wb.active
    all_route_data = {
        "CZ_CAN-DAC": {
            "currency": "CNY",
            "fs_taxes": {
                "base_currency": "CNY",
                "equ_currency": "BDT",
                "exchange_rate": 17.998,
                "yq_charge": 492.0,
                "yr_charge": 7200.0,
                "q_charge": 28.97,
                "roe": 6.901808,
                "total_taxes": 9312.0,
                "total_amount": 26771.0,
                "tax_breakdown": {"CN": 1620.0},
            },
            "rbd_data": {
                "Q": {"ow_fare": 770, "rt_fare": 1400},
            },
        }
    }
    sections = {
        ("CAN", "outbound"): [
            ("CZ", "DAC", "CZ_CAN-DAC", all_route_data["CZ_CAN-DAC"])
        ]
    }

    _write_individual_tables_sheet(
        ws,
        all_route_data,
        sections,
        {"CZ": "China Southern"},
        {"DAC": "Dhaka", "CAN": "Guangzhou"},
        RBD_SORT_ORDER,
        ["DAC"],
        None,
    )

    # Find the header row by scanning for "RBD".
    header_row = next(
        r
        for r in range(1, ws.max_row + 1)
        if ws.cell(row=r, column=1).value == "RBD"
    )
    headers = [
        ws.cell(row=header_row, column=c).value
        for c in range(1, ws.max_column + 1)
        if isinstance(ws.cell(row=header_row, column=c).value, str)
    ]
    assert "OW/Gross(CNY)" in headers, (
        f"Non-DAC origin must use base currency for gross, got headers: {headers}"
    )
    assert "RT/Gross(CNY)" in headers, (
        f"Non-DAC origin must use base currency for gross, got headers: {headers}"
    )


# ── v1.5.18: per-sheet currency rules for YQ/YR/Q ─────────────────────────────


def _cz_can_dac_route_data() -> dict:
    """Build a route_data dict matching the CZ CAN-DAC example from the
    user-supplied screenshot:

        Q CANDAC28.97  (NUC=USD)
        FARE CNY970 EQU BDT17459 CN1620 YQ492 YR7200 TAXES BDT9312 TOT BDT26771

    Expected derived values:
        exchange_rate = 17459/970 = 17.998 BDT/CNY
        roe = 6.901808 CNY/NUC
        Q in CNY = 28.97 × 6.901808 ≈ 199.94
        Q in BDT = 28.97 × 6.901808 × 17.998 ≈ 3598.85
    """
    return {
        "CZ_CAN-DAC": {
            "currency": "CNY",
            "fs_taxes": {
                "base_currency": "CNY",
                "equ_currency": "BDT",
                "base_fare": 970.0,
                "equ_fare": 17459.0,
                "exchange_rate": round(17459 / 970, 4),
                "roe": 6.901808,
                "yq_charge": 492.0,
                "yr_charge": 7200.0,
                "q_charge": 28.97,
                "total_taxes": 9312.0,
                "total_amount": 26771.0,
                "tax_breakdown": {"CN": 1620.0},
            },
            "rbd_data": {
                "Q": {"ow_fare": 770, "rt_fare": 1400},
            },
        }
    }


def test_tax_breakdown_sheet_displays_q_in_bdt_via_roe_and_exchange_rate():
    """Tax Breakdowns sheet stays in BDT — its respective currency.  Q is
    parsed in NUC (USD) and must be converted: q_bdt = q_usd × roe ×
    exchange_rate.  YQ / YR / tax codes / totals stay raw (already BDT)."""
    wb = Workbook()
    ws = wb.active
    all_route_data = _cz_can_dac_route_data()
    sections = {
        ("CAN", "outbound"): [
            ("CZ", "DAC", "CZ_CAN-DAC", all_route_data["CZ_CAN-DAC"])
        ]
    }

    _write_tax_breakdown_sheet(
        ws,
        all_route_data,
        sections,
        {"CZ": "China Southern"},
        {"DAC": "Dhaka", "CAN": "Guangzhou"},
        ["DAC"],
    )

    # Find the rows by scanning for the labels — sheet layout has dynamic
    # row offsets depending on section/title rows above.
    cells = {
        ws.cell(row=r, column=c).value: ws.cell(row=r, column=c + 1).value
        for r in range(1, ws.max_row + 1)
        for c in range(1, ws.max_column + 1)
        if ws.cell(row=r, column=c).value
        in {"YQ", "YR", "Q", "Total Taxes", "Total Amount", "CN"}
    }

    assert cells["YQ"] == 492.0  # raw BDT
    assert cells["YR"] == 7200.0  # raw BDT
    # Q in BDT = 28.97 × 6.901808 × (17459/970)  ≈ 3598.85 BDT
    expected_q_bdt = 28.97 * 6.901808 * (17459 / 970)
    assert abs(cells["Q"] - expected_q_bdt) < 0.01
    assert cells["CN"] == 1620.0  # raw BDT
    assert cells["Total Taxes"] == 9312.0
    assert cells["Total Amount"] == 26771.0


def test_tax_breakdown_sheet_header_stays_in_equ_cur_bdt():
    """Header on the Tax Breakdowns sheet must read `Amount (BDT)`, NOT
    `Amount ({base_cur})`.  This is the bug the user caught — the sheet
    was wrongly switched to base currency in the first v1.5.17 attempt."""
    wb = Workbook()
    ws = wb.active
    all_route_data = _cz_can_dac_route_data()
    sections = {
        ("CAN", "outbound"): [
            ("CZ", "DAC", "CZ_CAN-DAC", all_route_data["CZ_CAN-DAC"])
        ]
    }

    _write_tax_breakdown_sheet(
        ws,
        all_route_data,
        sections,
        {"CZ": "China Southern"},
        {"DAC": "Dhaka", "CAN": "Guangzhou"},
        ["DAC"],
    )

    headers = [
        ws.cell(row=r, column=c).value
        for r in range(1, ws.max_row + 1)
        for c in range(1, ws.max_column + 1)
        if isinstance(ws.cell(row=r, column=c).value, str)
        and ws.cell(row=r, column=c).value.startswith("Amount")
    ]

    assert headers, "Expected at least one Amount(...) header"
    assert all(h == "Amount (BDT)" for h in headers), (
        f"Tax Breakdowns header must say 'Amount (BDT)', got {headers!r}"
    )


def test_yq_charges_sheet_q_in_base_via_roe_not_via_exchange_rate():
    """YQ-YR-Q Charges sheet — entire sheet in fare's *base* currency.
    Q must use × roe (USD → base), NOT ÷ exch_rate (which would treat Q
    as if it were BDT-denominated and shrink it by ~125× on a CNY fare).
    YQ / YR are scraped in BDT so they DO divide by exch_rate."""
    wb = Workbook()
    ws = wb.active
    all_route_data = _cz_can_dac_route_data()
    sections = {
        ("CAN", "outbound"): [
            ("CZ", "DAC", "CZ_CAN-DAC", all_route_data["CZ_CAN-DAC"])
        ]
    }

    _write_yq_charges_sheet(
        ws,
        all_route_data,
        sections,
        {"CZ": "China Southern"},
        {"DAC": "Dhaka", "CAN": "Guangzhou"},
        ["DAC"],
    )

    cells = {
        ws.cell(row=r, column=c).value: ws.cell(row=r, column=c + 1).value
        for r in range(1, ws.max_row + 1)
        for c in range(1, ws.max_column + 1)
        if ws.cell(row=r, column=c).value in {"YQ", "YR", "Q"}
    }

    rate = 17459 / 970
    # YQ in CNY = 492 / rate ≈ 27.33
    expected_yq_cny = round(492 / rate, 2)
    expected_yr_cny = round(7200 / rate, 2)
    # Q in CNY = 28.97 × 6.901808 ≈ 199.94 — NOT 28.97 / rate ≈ 1.61.
    expected_q_cny = round(28.97 * 6.901808, 2)
    assert cells["YQ"] == expected_yq_cny
    assert cells["YR"] == expected_yr_cny
    assert cells["Q"] == expected_q_cny, (
        f"Q in YQ-YR-Q sheet must be q_usd × roe (got {cells['Q']!r}, "
        f"expected ≈ {expected_q_cny}).  If this fails the regression is "
        f"the same one user caught: Q being divided by exch_rate."
    )


def test_yq_charges_sheet_header_uses_base_currency():
    """The YQ-YR-Q Charges sheet header must reflect the fare's base
    currency, not BDT — for CZ CAN-DAC that's `Amount (CNY)`."""
    wb = Workbook()
    ws = wb.active
    all_route_data = _cz_can_dac_route_data()
    sections = {
        ("CAN", "outbound"): [
            ("CZ", "DAC", "CZ_CAN-DAC", all_route_data["CZ_CAN-DAC"])
        ]
    }

    _write_yq_charges_sheet(
        ws,
        all_route_data,
        sections,
        {"CZ": "China Southern"},
        {"DAC": "Dhaka", "CAN": "Guangzhou"},
        ["DAC"],
    )

    headers = [
        ws.cell(row=r, column=c).value
        for r in range(1, ws.max_row + 1)
        for c in range(1, ws.max_column + 1)
        if isinstance(ws.cell(row=r, column=c).value, str)
        and ws.cell(row=r, column=c).value.startswith("Amount")
    ]
    assert headers, "Expected at least one Amount(...) header"
    assert all(h == "Amount (CNY)" for h in headers), (
        f"YQ-YR-Q header must say 'Amount (CNY)' for CNY-base fare, got {headers!r}"
    )
