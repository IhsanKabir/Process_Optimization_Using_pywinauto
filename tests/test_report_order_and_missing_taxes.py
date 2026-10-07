"""Fare report: route/airline ordering, missing-tax flags and original-currency
tax amounts."""

from openpyxl import Workbook, load_workbook

from excel_report import (
    _airline_sort_key,
    _collect_missing_tax_routes,
    _section_sort_key,
    _write_individual_tables_sheet,
    _write_tax_breakdown_sheet,
    generate_report,
)

TAXES = {
    "base_currency": "USD",
    "base_fare": 300.0,
    "equ_currency": "BDT",
    "equ_fare": 36000.0,
    "exchange_rate": 120.0,
    "roe": 1.0,
    "yq_charge": 1200.0,
    "yr_charge": 0.0,
    "q_charge": 10.0,
    "total_taxes": 6000.0,
    "total_amount": 42000.0,
    "tax_breakdown": {"BD": 3000.0, "E5": 600.0},
}
FARES = {"Y": {"ow_fare": 300, "rt_fare": 550}}


def _route(fs_taxes=None, fares=FARES):
    return {"currency": "USD", "fs_taxes": dict(fs_taxes or {}), "rbd_data": fares}


def _titles(ws, row):
    return [
        ws.cell(row=row, column=c).value
        for c in range(1, ws.max_column + 1)
        if ws.cell(row=row, column=c).value
    ]


def _header_row(ws, col=1):
    return next(r for r in range(1, ws.max_row + 1) if ws.cell(r, col).value == "RBD")


# ── ordering ────────────────────────────────────────────────────────────────


def test_outbound_section_comes_before_inbound():
    keys = [("BKK", "inbound"), ("BKK", "outbound"), ("CCU", "inbound")]

    assert sorted(keys, key=_section_sort_key) == [
        ("BKK", "outbound"),
        ("BKK", "inbound"),
        ("CCU", "inbound"),
    ]


def test_bs_then_bg_then_alphabetical():
    airlines = ["UL", "BG", "8D", "BS", "EK"]

    assert sorted(airlines, key=_airline_sort_key) == ["BS", "BG", "8D", "EK", "UL"]


def test_main_report_lists_dac_bkk_before_bkk_dac_and_bs_first(tmp_path):
    data = {
        "BG_BKK-DAC": _route(TAXES),
        "BS_BKK-DAC": _route(TAXES),
        "BG_DAC-BKK": _route(TAXES),
        "BS_DAC-BKK": _route(TAXES),
    }
    out = str(tmp_path / "fares.xlsx")

    generate_report(data, out, config={"domestic_airports": ["DAC"]})

    ws = load_workbook(out)["Individual Tables"]
    titles = [
        ws.cell(r, c).value
        for r in range(1, ws.max_row + 1)
        for c in range(1, ws.max_column + 1)
        if isinstance(ws.cell(r, c).value, str) and " / " in ws.cell(r, c).value
    ]
    assert [t.split()[0:3] for t in titles] == [
        ["BS", "/", "DAC-BKK"],
        ["BG", "/", "DAC-BKK"],
        ["BS", "/", "BKK-DAC"],
        ["BG", "/", "BKK-DAC"],
    ]


# ── missing taxes ───────────────────────────────────────────────────────────


def _individual(all_route_data, route_key):
    wb = Workbook()
    ws = wb.active
    airline, route = route_key.split("_")
    origin, dest = route.split("-")
    intl, direction = (dest, "outbound") if origin == "DAC" else (origin, "inbound")
    sections = {
        (intl, direction): [(airline, "DAC", route_key, all_route_data[route_key])]
    }
    _write_individual_tables_sheet(
        ws, all_route_data, sections, {}, {}, [], ["DAC"], None
    )
    return ws


# Return leg with different charges: YQ 600, YR 600, Q 5 NUC, tax 5,000 BDT.
RETURN_TAXES = dict(
    TAXES, yq_charge=600.0, yr_charge=600.0, q_charge=5.0, total_taxes=5000.0
)


def _row(ws, rbd):
    r = next(r for r in range(1, ws.max_row + 1) if ws.cell(r, 1).value == rbd)
    return [ws.cell(r, c).value for c in range(1, 8)]


def test_complete_legs_formulas():
    data = {"BS_DAC-BKK": _route(TAXES), "BS_BKK-DAC": _route(RETURN_TAXES)}

    ws = _individual(data, "BS_DAC-BKK")

    assert _titles(ws, _header_row(ws)) == [
        "RBD",
        "OW/USD",
        "With YQ/OW(USD)",
        "OW/Gross(BDT)",
        "RT/USD",
        "With YQ/RT(USD)",
        "RT/Gross(BDT)",
    ]
    # R=120, Q = 10 NUC x ROE 1 x 120 = 1,200 BDT.
    # With YQ/OW = 300 + 1200/120. OW gross (BDT, from DAC) = 300*120 + 6000 + Q.
    # With YQ/RT = 550 + 2*1200/120.
    # RT gross = 550*120 + gov (4800 + 3800) + 2*(1200+0) + Q once = 78,200.
    assert _row(ws, "Y") == ["Y", "300", "310", "43,200", "550", "570", "78,200"]
    assert "INCOMPLETE" not in ws.cell(_header_row(ws) - 2, 1).value


def test_missing_leg_taxes_blank_all_derived_columns_and_flag():
    data = {"BS_DAC-BKK": _route({}), "BS_BKK-DAC": _route(RETURN_TAXES)}

    ws = _individual(data, "BS_DAC-BKK")

    hr = _header_row(ws)
    assert _titles(ws, hr) == ["RBD", "OW/USD", "RT/USD"]
    title = ws.cell(hr - 2, 1)
    assert "INCOMPLETE" in title.value and "no tax breakdown" in title.value
    assert title.fill.start_color.rgb.endswith("FFC7CE")


def test_missing_return_leg_blanks_only_rt_gross():
    data = {"BS_DAC-BKK": _route(TAXES), "BS_BKK-DAC": _route({})}

    ws = _individual(data, "BS_DAC-BKK")

    hr = _header_row(ws)
    assert _titles(ws, hr) == [
        "RBD",
        "OW/USD",
        "With YQ/OW(USD)",
        "OW/Gross(BDT)",
        "RT/USD",
        "With YQ/RT(USD)",
    ]
    assert "return leg BKK-DAC" in ws.cell(hr - 2, 1).value


def test_unextracted_return_route_blanks_rt_gross():
    data = {"BS_DAC-BKK": _route(TAXES)}

    ws = _individual(data, "BS_DAC-BKK")

    assert _titles(ws, _header_row(ws))[-1] == "With YQ/RT(USD)"
    assert "not extracted" in ws.cell(_header_row(ws) - 2, 1).value


def test_fd_and_fs_currency_mismatch_is_not_converted():
    # FD fares in THB but the FS option was priced in USD: the USD rate
    # must not be applied to THB fares.
    thb_route = dict(_route(TAXES), currency="THB")
    data = {"TG_BKK-DAC": thb_route, "TG_DAC-BKK": _route(TAXES)}

    ws = _individual(data, "TG_BKK-DAC")

    assert _titles(ws, _header_row(ws)) == ["RBD", "OW/THB", "RT/THB"]
    assert "THB" in ws.cell(_header_row(ws) - 2, 1).value


def test_rate_fallback_without_equ_line_is_incomplete():
    no_equ = dict(TAXES, equ_fare=0.0, equ_currency=None, exchange_rate=1.0)
    data = {"BS_DAC-BKK": _route(no_equ), "BS_BKK-DAC": _route(TAXES)}

    ws = _individual(data, "BS_DAC-BKK")

    assert _titles(ws, _header_row(ws)) == ["RBD", "OW/USD", "RT/USD"]
    assert "exchange rate" in ws.cell(_header_row(ws) - 2, 1).value


def test_collect_missing_lists_reason_and_unextracted_return_route():
    data = {
        "BG_BKK-DAC": _route({}),
        "BS_DAC-BKK": _route({}),
        "UL_DAC-CMB": _route({}, fares={}),
        "BS_BKK-DAC": _route(TAXES),
        "EK_DAC-DXB": _route(TAXES),
    }

    missing = _collect_missing_tax_routes(data, ["DAC"])

    assert [(m["airline"], m["route"], m["missing"]) for m in missing] == [
        ("BS", "DAC-BKK", "no tax breakdown"),
        ("BG", "BKK-DAC", "no tax breakdown"),
        ("BG", "DAC-BKK", "return route not extracted"),
        ("EK", "DXB-DAC", "return route not extracted"),
    ]
    one_way = _collect_missing_tax_routes(data, ["DAC"], return_legs_expected=False)
    assert [m["route"] for m in one_way] == ["DAC-BKK", "BKK-DAC"]


def test_report_has_rerun_sheet_only_when_taxes_missing(tmp_path):
    out = str(tmp_path / "fares.xlsx")
    generate_report(
        {"BS_DAC-BKK": _route({}), "BS_BKK-DAC": _route(TAXES)},
        out,
        config={"domestic_airports": ["DAC"]},
    )

    wb = load_workbook(out)
    assert wb.sheetnames[1] == "Re-run Needed"
    rows = [r for r in wb["Re-run Needed"].iter_rows(values_only=True) if any(r)]
    assert ("BS", "DAC-BKK") in [(r[0], r[1]) for r in rows]

    clean = str(tmp_path / "clean.xlsx")
    generate_report(
        {"BS_DAC-BKK": _route(TAXES), "BS_BKK-DAC": _route(TAXES)},
        clean,
        config={"domestic_airports": ["DAC"]},
    )
    assert "Re-run Needed" not in load_workbook(clean).sheetnames


def test_fd_only_runs_do_not_flag_missing_taxes(tmp_path):
    out = str(tmp_path / "fd_only.xlsx")

    generate_report(
        {"BS_DAC-BKK": _route({}), "BS_BKK-DAC": _route({})},
        out,
        config={"domestic_airports": ["DAC"]},
        taxes_expected=False,
    )

    wb = load_workbook(out)
    assert "Re-run Needed" not in wb.sheetnames
    texts = [
        v
        for row in wb["Individual Tables"].iter_rows(values_only=True)
        for v in row
        if isinstance(v, str)
    ]
    assert not any("INCOMPLETE" in t for t in texts)


# ── original currency on Tax Breakdowns ─────────────────────────────────────


def test_tax_breakdown_shows_original_currency_beside_bdt():
    wb = Workbook()
    ws = wb.active
    data = {"BS_DAC-BKK": _route(TAXES)}
    sections = {("BKK", "outbound"): [("BS", "DAC", "BS_DAC-BKK", data["BS_DAC-BKK"])]}

    _write_tax_breakdown_sheet(ws, data, sections, {}, {}, ["DAC"])

    rows = {
        ws.cell(r, 1).value: (ws.cell(r, 2).value, ws.cell(r, 3).value)
        for r in range(1, ws.max_row + 1)
    }
    header_row = next(
        r for r in range(1, ws.max_row + 1) if ws.cell(r, 1).value == "Tax/Charge"
    )
    assert ws.cell(header_row, 2).value == "Amount (BDT)"
    assert ws.cell(header_row, 3).value == "Original (USD)"
    assert rows["BD"] == (3000.0, 25.0)
    assert rows["YQ"] == (1200.0, 10.0)
    assert rows["Q"][1] == 10.0  # NUC 10 x ROE 1
    assert rows["Total Taxes"] == (6000.0, 50.0)


def test_rt_gross_uses_starting_legs_carrier_charges_twice():
    """flydubai DXB-DAC-DXB, checked against the real RT ticket:
    TAXES BDT26000 = gov taxes 4,545 (DXB) + 10,087 (DAC) + 2 x (YQ 3,089 +
    YR 2,595). The DAC-DXB one-way (sold from Dhaka) has YQ 0, so adding the
    two one-way TAXES (10,229 + 12,682) would be 3,089 short."""
    dxb_dac = {
        "base_currency": "AED",
        "base_fare": 590.0,
        "equ_currency": "BDT",
        "equ_fare": 19850.0,
        "exchange_rate": 33.6441,
        "yq_charge": 3089.0,
        "yr_charge": 2595.0,
        "total_taxes": 10229.0,
        "tax_breakdown": {"AE": 2524.0, "F6": 1683.0, "TP": 169.0, "ZR": 169.0},
    }
    dac_dxb = {
        "base_currency": "USD",
        "base_fare": 653.0,
        "equ_currency": "BDT",
        "equ_fare": 80672.0,
        "exchange_rate": 123.5406,
        "yq_charge": 0.0,
        "yr_charge": 2595.0,
        "total_taxes": 12682.0,
        "tax_breakdown": {"BD": 500.0, "OW": 2500.0, "UT": 4000.0, "E5": 446.0},
    }
    data = {
        "FZ_DXB-DAC": {
            "currency": "AED",
            "fs_taxes": dxb_dac,
            "rbd_data": {"K": {"ow_fare": 760, "rt_fare": 1220}},
        },
        "FZ_DAC-DXB": {
            "currency": "USD",
            "fs_taxes": dac_dxb,
            "rbd_data": {"K": {"ow_fare": 300, "rt_fare": 560}},
        },
    }

    ws = _individual(data, "FZ_DXB-DAC")

    # RT gross (AED) = 1220 + 26000 / 33.6441 = 1992.8
    assert _row(ws, "K")[-1] == "1,993"


def _one_way_route(fs, fare, currency):
    return {
        "currency": currency,
        "fs_taxes": fs,
        "rbd_data": {"X": {"ow_fare": fare, "rt_fare": None}},
    }


def test_ow_gross_matches_smartpoint_total_for_real_tickets():
    """Gross = fare + Q + taxes should land on Smartpoint's TOT, apart from
    the fare rounding (FD shows the rounded fare without Q)."""
    # flydubai DXB-DAC L: FD 540 AED (145.10 NUC), Q 14.51 NUC, TOT BDT30079.
    fz = {
        "base_currency": "AED",
        "base_fare": 590.0,
        "equ_currency": "BDT",
        "equ_fare": 19850.0,
        "exchange_rate": 33.6441,
        "roe": 3.673315,
        "q_charge": 14.51,
        "yq_charge": 3089.0,
        "yr_charge": 2595.0,
        "total_taxes": 10229.0,
        "tax_breakdown": {"AE": 2524.0},
    }
    # Emirates DAC-ZVJ L: FD 365 USD, Q 2.60 NUC, TOT BDT55550 (DAC origin: BDT).
    ek = {
        "base_currency": "USD",
        "base_fare": 368.0,
        "equ_currency": "BDT",
        "equ_fare": 45463.0,
        "exchange_rate": 123.5408,
        "roe": 1.0,
        "q_charge": 2.60,
        "total_taxes": 10087.0,
        "tax_breakdown": {"BD": 500.0},
    }
    fz_ws = _individual({"FZ_DXB-DAC": _one_way_route(fz, 540, "AED")}, "FZ_DXB-DAC")
    ek_ws = _individual({"EK_DAC-ZVJ": _one_way_route(ek, 365, "USD")}, "EK_DAC-ZVJ")

    fz_gross = float(_row(fz_ws, "X")[3].replace(",", ""))
    ek_gross = float(_row(ek_ws, "X")[3].replace(",", ""))

    # TOT 30079 / 33.6441 = 894 AED; FD rounds 533 up to 540 (+7 - 4 rounding).
    assert abs(fz_gross - 30079 / 33.6441) <= 5
    # TOT 55,550 BDT; Smartpoint rounds 367.60 up to 368 (49 BDT).
    assert abs(ek_gross - 55550) <= 50


def test_q_without_roe_on_non_usd_fare_is_incomplete():
    aed = dict(TAXES, base_currency="AED", roe=1.0, q_charge=14.51)
    route = dict(_route(aed), currency="AED")
    data = {"FZ_DXB-DAC": route, "FZ_DAC-DXB": _route(TAXES)}

    ws = _individual(data, "FZ_DXB-DAC")

    assert "ROE" in ws.cell(_header_row(ws) - 2, 1).value
