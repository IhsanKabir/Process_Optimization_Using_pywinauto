"""
excel_report.py - Fare Report Generator with Comparison Dashboard

Groups routes by international destination, placing fares from all
domestic airports (DAC, CGP, ZYL, CXB) side-by-side.

Layout per section:
    → Doha (DOH) [QAR]
    RBD | BG DAC OW | BG DAC RT | BS DAC OW | BS DAC RT | BG CGP OW | BG CGP RT | ...
"""

import os
from collections import OrderedDict
from datetime import datetime
from typing import Optional

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Border, Side, Alignment
from openpyxl.utils import get_column_letter

from origin_sensitive_taxes import compute_rt_tax_total

# ── Styles ──────────────────────────────────────────────
THIN_BORDER = Border(
    left=Side(style="thin"),
    right=Side(style="thin"),
    top=Side(style="thin"),
    bottom=Side(style="thin"),
)
HEADER_FONT = Font(name="Calibri", bold=True, size=11, color="FFFFFF")
HEADER_FILL = PatternFill(start_color="2F5496", end_color="2F5496", fill_type="solid")
ROUTE_FONT = Font(name="Calibri", bold=True, size=13)
ROUTE_FILL = PatternFill(start_color="D6E4F0", end_color="D6E4F0", fill_type="solid")

INCREASE_FONT = Font(name="Calibri", size=11, color="CC0000")
DECREASE_FONT = Font(name="Calibri", size=11, color="006100")
NEW_FONT = Font(name="Calibri", size=11, color="7F6000")
SOLD_OUT_FONT = Font(name="Calibri", size=11, color="808080", italic=True)

INCREASE_FILL = PatternFill(start_color="FDE9E9", end_color="FDE9E9", fill_type="solid")
DECREASE_FILL = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid")
NEW_FILL = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
SOLD_OUT_FILL = PatternFill(start_color="D9D9D9", end_color="D9D9D9", fill_type="solid")

MAIN_SHEET = "Side-by-Side Comparison"

UPPER_CABIN_PRIORITY = {
    "FIRST": 0,
    "PREMIUM BUSINESS": 1,
    "BUSINESS": 2,
}

AIRLINE_CABIN_RBDS = {
    "EK": OrderedDict(
        [
            ("FIRST", ["F", "Z", "A"]),
            ("BUSINESS", ["J", "D", "C", "I", "O", "P", "H"]),
        ]
    ),
    "BG": OrderedDict(
        [
            ("BUSINESS", ["J", "C", "D", "R", "Z"]),
            ("PREMIUM ECONOMY", ["W"]),
            (
                "ECONOMY",
                [
                    "K",
                    "V",
                    "O",
                    "G",
                    "Q",
                    "S",
                    "T",
                    "I",
                    "X",
                    "Y",
                    "A",
                    "N",
                    "P",
                    "U",
                    "L",
                    "H",
                    "M",
                    "B",
                    "E",
                ],
            ),
        ]
    ),
    "BS": OrderedDict(
        [
            ("FIRST", ["F"]),
            ("BUSINESS", ["P", "Z", "D", "C", "J"]),
        ]
    ),
    "QR": OrderedDict(
        [
            ("FIRST", ["F", "A", "Z"]),
            ("BUSINESS", ["J", "C", "D", "I", "U", "R", "P"]),
            (
                "ECONOMY",
                [
                    "T",
                    "G",
                    "O",
                    "E",
                    "X",
                    "W",
                    "Y",
                    "B",
                    "H",
                    "K",
                    "M",
                    "L",
                    "V",
                    "S",
                    "N",
                    "Q",
                ],
            ),
        ]
    ),
    "OD": OrderedDict(
        [
            ("FIRST", ["P", "F", "A"]),
            ("BUSINESS", ["J", "C", "D", "I", "Z"]),
        ]
    ),
    "MH": OrderedDict(
        [
            ("PREMIUM BUSINESS", ["P", "F", "A"]),
            ("BUSINESS", ["J", "C", "D", "I", "Z", "U", "W"]),
            (
                "ECONOMY",
                [
                    "R",
                    "T",
                    "E",
                    "Y",
                    "B",
                    "H",
                    "K",
                    "M",
                    "L",
                    "V",
                    "S",
                    "N",
                    "Q",
                    "O",
                    "X",
                    "G",
                ],
            ),
        ]
    ),
    "SQ": OrderedDict(
        [
            ("FIRST", ["F", "A", "O"]),
            ("BUSINESS", ["Z", "C", "J", "U", "D", "I"]),
            ("PREMIUM ECONOMY", ["S", "T", "P", "L", "R"]),
            ("ECONOMY", ["X", "G", "Y", "B", "E", "M", "H", "W", "Q", "N", "V", "K"]),
        ]
    ),
    "TG": OrderedDict(
        [
            ("FIRST", ["F", "A", "P", "O"]),
            ("BUSINESS", ["C", "D", "J", "Z", "I", "R"]),
            ("PREMIUM ECONOMY", ["U", "E"]),
            (
                "ECONOMY",
                ["W", "L", "N", "Y", "B", "M", "H", "Q", "T", "K", "S", "X", "V"],
            ),
        ]
    ),
    "8D": OrderedDict(
        [
            ("FIRST", ["P", "F", "A"]),
            ("BUSINESS", ["J", "C", "D", "I", "Z"]),
            ("PREMIUM ECONOMY", ["W", "E"]),
            (
                "ECONOMY",
                [
                    "S",
                    "Y",
                    "B",
                    "H",
                    "K",
                    "L",
                    "M",
                    "N",
                    "Q",
                    "T",
                    "V",
                    "X",
                    "R",
                    "U",
                    "G",
                    "O",
                ],
            ),
        ]
    ),
    "Q2": OrderedDict(
        [
            ("BUSINESS", ["J", "C", "I", "D"]),
            ("PREMIUM ECONOMY", ["K", "P", "F", "W"]),
            (
                "ECONOMY",
                [
                    "V",
                    "E",
                    "A",
                    "H",
                    "N",
                    "U",
                    "X",
                    "G",
                    "S",
                    "Y",
                    "B",
                    "R",
                    "M",
                    "Z",
                    "L",
                    "Q",
                    "O",
                    "T",
                ],
            ),
        ]
    ),
    "AI": OrderedDict(
        [
            ("FIRST", ["F", "O"]),
            ("BUSINESS", ["C", "D", "J", "Z", "I"]),
            ("PREMIUM ECONOMY", ["R", "A", "N", "E"]),
            (
                "ECONOMY",
                [
                    "U",
                    "T",
                    "S",
                    "X",
                    "P",
                    "Y",
                    "B",
                    "M",
                    "H",
                    "K",
                    "Q",
                    "V",
                    "W",
                    "G",
                    "L",
                ],
            ),
        ]
    ),
    "6E": OrderedDict(
        [
            ("FIRST", ["P", "F", "A"]),
            ("BUSINESS", ["J", "C", "D", "I", "Z"]),
            ("PREMIUM ECONOMY", ["W", "E"]),
            (
                "ECONOMY",
                [
                    "S",
                    "Y",
                    "B",
                    "H",
                    "K",
                    "L",
                    "M",
                    "N",
                    "Q",
                    "T",
                    "V",
                    "X",
                    "R",
                    "U",
                    "G",
                    "O",
                ],
            ),
        ]
    ),
    "SV": OrderedDict(
        [
            ("FIRST", ["F", "P", "A", "R", "W"]),
            ("BUSINESS", ["J", "C", "D", "I", "O", "Z"]),
            (
                "ECONOMY",
                [
                    "V",
                    "X",
                    "S",
                    "U",
                    "G",
                    "Y",
                    "B",
                    "M",
                    "H",
                    "E",
                    "K",
                    "L",
                    "Q",
                    "N",
                    "T",
                ],
            ),
        ]
    ),
    "FZ": OrderedDict(
        [
            ("BUSINESS", ["J", "C", "Z", "D", "P"]),
            (
                "ECONOMY",
                [
                    "B",
                    "U",
                    "K",
                    "H",
                    "Q",
                    "L",
                    "V",
                    "GA",
                    "GB",
                    "GC",
                    "GD",
                    "GE",
                    "GF",
                    "GG",
                    "GH",
                    "GI",
                    "GJ",
                    "GK",
                    "GL",
                    "GM",
                    "GN",
                    "GO",
                    "GP",
                    "GQ",
                    "GR",
                    "GS",
                    "GT",
                    "GU",
                    "GV",
                    "GW",
                    "GX",
                    "GY",
                    "GZ",
                    "G",
                    "Y",
                    "A",
                    "I",
                    "E",
                    "O",
                    "W",
                    "T",
                    "M",
                    "N",
                    "R",
                ],
            ),
        ]
    ),
    "G9": OrderedDict(
        [
            (
                "ECONOMY",
                [
                    "E",
                    "Y",
                    "H",
                    "M",
                    "B",
                    "N",
                    "Q",
                    "S",
                    "T",
                    "U",
                    "V",
                    "W",
                    "X",
                    "K",
                    "R",
                ],
            ),
        ]
    ),
    "WY": OrderedDict(
        [
            ("FIRST", ["F", "A"]),
            ("BUSINESS", ["J", "C", "D", "I", "P", "Z", "U"]),
            (
                "ECONOMY",
                [
                    "O",
                    "R",
                    "T",
                    "E",
                    "W",
                    "X",
                    "G",
                    "Y",
                    "B",
                    "H",
                    "K",
                    "M",
                    "L",
                    "V",
                    "S",
                    "N",
                    "Q",
                ],
            ),
        ]
    ),
    "GF": OrderedDict(
        [
            ("BUSINESS", ["J", "C", "D", "I", "P", "R"]),
            (
                "ECONOMY",
                [
                    "Q",
                    "V",
                    "E",
                    "O",
                    "N",
                    "S",
                    "W",
                    "Z",
                    "Y",
                    "H",
                    "M",
                    "L",
                    "B",
                    "K",
                    "X",
                    "G",
                    "U",
                    "T",
                ],
            ),
        ]
    ),
    "CZ": OrderedDict(
        [
            ("FIRST", ["F"]),
            ("BUSINESS", ["J", "C", "D", "I", "O"]),
            ("PREMIUM ECONOMY", ["W", "S"]),
            (
                "ECONOMY",
                [
                    "E",
                    "V",
                    "Z",
                    "T",
                    "N",
                    "R",
                    "G",
                    "X",
                    "Y",
                    "P",
                    "B",
                    "M",
                    "H",
                    "K",
                    "U",
                    "A",
                    "L",
                    "Q",
                ],
            ),
        ]
    ),
    "UL": OrderedDict(
        [
            ("BUSINESS", ["J", "C", "D", "I", "Z", "U"]),
            (
                "ECONOMY",
                [
                    "X",
                    "V",
                    "S",
                    "N",
                    "Q",
                    "O",
                    "G",
                    "T",
                    "Y",
                    "B",
                    "P",
                    "H",
                    "K",
                    "W",
                    "M",
                    "E",
                    "L",
                    "R",
                ],
            ),
        ]
    ),
    "OV": OrderedDict(
        [
            ("FIRST", ["P", "F", "A"]),
            ("BUSINESS", ["J", "C", "D", "I", "Z"]),
            ("PREMIUM ECONOMY", ["W", "E"]),
        ]
    ),
    "F3": OrderedDict(
        [
            (
                "ECONOMY",
                [
                    "A",
                    "B",
                    "C",
                    "D",
                    "E",
                    "F",
                    "G",
                    "H",
                    "I",
                    "J",
                    "K",
                    "L",
                    "M",
                    "N",
                    "O",
                    "P",
                    "Q",
                    "R",
                    "S",
                    "T",
                ],
            ),
        ]
    ),
    "AK": OrderedDict(
        [
            ("FIRST", ["P", "F", "A"]),
            ("BUSINESS", ["J", "C", "D", "I", "Z"]),
            ("PREMIUM ECONOMY", ["W", "E"]),
            (
                "ECONOMY",
                [
                    "S",
                    "Y",
                    "B",
                    "H",
                    "K",
                    "L",
                    "M",
                    "N",
                    "Q",
                    "T",
                    "V",
                    "X",
                    "R",
                    "U",
                    "G",
                    "O",
                ],
            ),
        ]
    ),
    "CA": OrderedDict(
        [
            ("FIRST", ["F", "A", "O"]),
            ("BUSINESS", ["J", "C", "D", "Z", "R", "I"]),
            ("PREMIUM ECONOMY", ["G", "E"]),
            (
                "ECONOMY",
                [
                    "L",
                    "P",
                    "X",
                    "N",
                    "K",
                    "Y",
                    "B",
                    "M",
                    "U",
                    "H",
                    "Q",
                    "V",
                    "W",
                    "S",
                    "T",
                ],
            ),
        ]
    ),
    "EY": OrderedDict(
        [
            ("FIRST", ["F", "A", "O"]),
            ("BUSINESS", ["J", "C", "D", "W", "Z", "P", "I", "X"]),
            (
                "ECONOMY",
                [
                    "T",
                    "N",
                    "S",
                    "R",
                    "G",
                    "Y",
                    "B",
                    "H",
                    "K",
                    "M",
                    "Q",
                    "L",
                    "V",
                    "U",
                    "E",
                ],
            ),
        ]
    ),
    "FD": OrderedDict(
        [
            ("FIRST", ["P", "F", "A"]),
            ("BUSINESS", ["J", "C", "D", "I", "Z"]),
            ("PREMIUM ECONOMY", ["W", "E"]),
            (
                "ECONOMY",
                [
                    "S",
                    "Y",
                    "B",
                    "H",
                    "K",
                    "L",
                    "M",
                    "N",
                    "Q",
                    "T",
                    "V",
                    "X",
                    "R",
                    "U",
                    "G",
                    "O",
                ],
            ),
        ]
    ),
    "IX": OrderedDict(
        [
            ("FIRST", ["P", "F", "A"]),
            ("BUSINESS", ["J", "C", "D", "I", "Z"]),
            ("PREMIUM ECONOMY", ["W", "E"]),
            (
                "ECONOMY",
                [
                    "S",
                    "Y",
                    "B",
                    "H",
                    "K",
                    "L",
                    "M",
                    "N",
                    "Q",
                    "T",
                    "V",
                    "X",
                    "R",
                    "U",
                    "G",
                    "O",
                ],
            ),
        ]
    ),
    "J9": OrderedDict(
        [
            ("BUSINESS", ["F", "C", "J", "D", "Z"]),
            (
                "ECONOMY",
                [
                    "K",
                    "B",
                    "U",
                    "E",
                    "W",
                    "T",
                    "R",
                    "P",
                    "A",
                    "Y",
                    "S",
                    "H",
                    "M",
                    "L",
                    "N",
                    "V",
                    "O",
                    "Q",
                    "I",
                ],
            ),
        ]
    ),
    "KU": OrderedDict(
        [
            ("FIRST", ["A", "F", "O", "Z", "R"]),
            ("BUSINESS", ["S", "C", "D", "J", "P", "I"]),
            (
                "ECONOMY",
                [
                    "B",
                    "E",
                    "G",
                    "H",
                    "K",
                    "L",
                    "M",
                    "N",
                    "Q",
                    "T",
                    "U",
                    "V",
                    "W",
                    "X",
                    "Y",
                ],
            ),
        ]
    ),
    "MU": OrderedDict(
        [
            ("FIRST", ["F", "A"]),
            ("PREMIUM BUSINESS", ["U"]),
            ("BUSINESS", ["J", "C", "D", "Q", "I", "O"]),
            ("PREMIUM ECONOMY", ["W", "P"]),
            (
                "ECONOMY",
                [
                    "V",
                    "T",
                    "G",
                    "Z",
                    "X",
                    "Y",
                    "B",
                    "M",
                    "E",
                    "H",
                    "K",
                    "L",
                    "N",
                    "R",
                    "S",
                ],
            ),
        ]
    ),
    "PG": OrderedDict(
        [
            ("BUSINESS", ["C", "D", "J", "Z"]),
            (
                "ECONOMY",
                [
                    "B",
                    "R",
                    "P",
                    "A",
                    "O",
                    "X",
                    "S",
                    "Y",
                    "M",
                    "K",
                    "N",
                    "T",
                    "L",
                    "H",
                    "Q",
                    "V",
                    "G",
                ],
            ),
        ]
    ),
    "PR": OrderedDict(
        [
            ("BUSINESS", ["J", "C", "D", "I", "Z", "A", "R"]),
            ("PREMIUM ECONOMY", ["W", "N"]),
            (
                "ECONOMY",
                [
                    "E",
                    "T",
                    "U",
                    "O",
                    "G",
                    "P",
                    "F",
                    "Y",
                    "S",
                    "L",
                    "M",
                    "H",
                    "Q",
                    "V",
                    "B",
                    "X",
                    "K",
                ],
            ),
        ]
    ),
    "QP": OrderedDict(
        [
            (
                "ECONOMY",
                [
                    "M",
                    "N",
                    "O",
                    "P",
                    "Q",
                    "R",
                    "T",
                    "U",
                    "V",
                    "Z",
                    "W",
                    "L",
                    "X",
                    "A",
                    "Y",
                    "B",
                    "C",
                    "D",
                    "E",
                    "F",
                    "H",
                    "I",
                    "J",
                    "K",
                ],
            ),
        ]
    ),
}


def _base_rbd(rbd):
    if not isinstance(rbd, str):
        return rbd
    return rbd.removesuffix(" (Unsaleable)")


def _format_rbd_label(rbd, is_unsaleable):
    base_rbd = _base_rbd(rbd)
    if is_unsaleable or base_rbd != rbd:
        return f"{base_rbd} (Unsaleable)"
    return base_rbd


def _fallback_rbd_order(rbd, rbd_sort_order):
    base_rbd = _base_rbd(rbd)
    try:
        return (0, rbd_sort_order.index(base_rbd), str(base_rbd))
    except ValueError:
        return (1, len(rbd_sort_order), str(base_rbd))


def _classify_rbd_for_airline(airline, rbd):
    base_rbd = _base_rbd(rbd)
    cabin_rules = AIRLINE_CABIN_RBDS.get((airline or "").upper())

    if not cabin_rules:
        return "ECONOMY", None

    for cabin, codes in cabin_rules.items():
        if base_rbd in codes:
            return cabin, codes.index(base_rbd)

    return "ECONOMY", None


def _group_rbds_by_cabin_break(rbds, airlines, rbd_sort_order):
    airline_codes = [airline for airline in airlines if airline]
    upper_rbds = []
    economy_rbds = []

    for rbd in rbds:
        classifications = [
            _classify_rbd_for_airline(airline, rbd) for airline in airline_codes
        ]
        if not classifications:
            classifications = [_classify_rbd_for_airline("", rbd)]

        has_upper_cabin = any(
            cabin in UPPER_CABIN_PRIORITY for cabin, _code_index in classifications
        )

        if has_upper_cabin:
            upper_rbds.append(rbd)
        else:
            economy_rbds.append(rbd)

    upper_rbds.sort(key=lambda item: _fallback_rbd_order(item, rbd_sort_order))
    economy_rbds.sort(key=lambda item: _fallback_rbd_order(item, rbd_sort_order))
    return upper_rbds, economy_rbds


def _precompute_rbd_lookups(entries, changes):
    """Pre-compute unsaleable set and best-fare dict in a single pass over entries."""
    unsaleable_set = set()
    best_fare_map = {}  # rbd -> max fare value

    for _airline, _domestic, route_key, route_info in entries:
        rbd_data = (
            route_info.get("rbd_data", route_info)
            if isinstance(route_info, dict) and "rbd_data" in route_info
            else route_info
        )
        if not isinstance(rbd_data, dict):
            continue

        for rbd, rbd_info in rbd_data.items():
            if not isinstance(rbd_info, dict):
                continue

            # Check unsaleable
            if "(Unsaleable)" in str(
                rbd_info.get("ow_fare_basis", "")
            ) or "(Unsaleable)" in str(rbd_info.get("rt_fare_basis", "")):
                unsaleable_set.add(rbd)

            # Collect fares
            for fare_key in ("ow_fare", "rt_fare"):
                fare = rbd_info.get(fare_key)
                if fare is not None:
                    best_fare_map[rbd] = max(best_fare_map.get(rbd, float("-inf")), fare)

            # Check sold_out changes
            change_info = changes.get(route_key, {}).get(rbd) if changes else None
            if change_info and change_info.get("type") == "sold_out":
                for fare_key in ("old_ow_fare", "old_rt_fare"):
                    fare = change_info.get(fare_key)
                    if fare is not None:
                        best_fare_map[rbd] = max(best_fare_map.get(rbd, float("-inf")), fare)

    return unsaleable_set, best_fare_map


def _is_unsaleable_rbd(unsaleable_set, rbd):
    return "(Unsaleable)" in str(rbd) or rbd in unsaleable_set


def _sort_rbd_bucket_by_fare(rbds, best_fare_map, rbd_sort_order):
    return sorted(
        rbds,
        key=lambda rbd: (
            -best_fare_map.get(rbd, float("-inf")),
            *_fallback_rbd_order(rbd, rbd_sort_order),
        ),
    )


def _partition_sorted_rbds(entries, rbds, airlines, rbd_sort_order, changes):
    upper_rbds, economy_rbds = _group_rbds_by_cabin_break(
        rbds, airlines, rbd_sort_order
    )

    unsaleable_set, best_fare_map = _precompute_rbd_lookups(entries, changes)

    upper_saleable = []
    economy_saleable = []
    unsaleable_rbds_list = []

    for rbd in upper_rbds:
        if _is_unsaleable_rbd(unsaleable_set, rbd):
            unsaleable_rbds_list.append(rbd)
        else:
            upper_saleable.append(rbd)

    for rbd in economy_rbds:
        if _is_unsaleable_rbd(unsaleable_set, rbd):
            unsaleable_rbds_list.append(rbd)
        else:
            economy_saleable.append(rbd)

    return (
        _sort_rbd_bucket_by_fare(upper_saleable, best_fare_map, rbd_sort_order),
        _sort_rbd_bucket_by_fare(economy_saleable, best_fare_map, rbd_sort_order),
        _sort_rbd_bucket_by_fare(unsaleable_rbds_list, best_fare_map, rbd_sort_order),
    )


def _has_tax_data_for_individual_table(fs_taxes):
    if not isinstance(fs_taxes, dict) or not fs_taxes:
        return False

    return any(
        [
            fs_taxes.get("tax_breakdown"),
            fs_taxes.get("total_taxes", 0),
            fs_taxes.get("yq_charge", 0),
            fs_taxes.get("yr_charge", 0),
            fs_taxes.get("q_charge", 0),
            fs_taxes.get("exchange_rate", 0),
        ]
    )


# ── Public API ──────────────────────────────────────────
def generate_report(
    all_route_data: dict,
    output_path: str,
    changes: Optional[dict] = None,
    config: Optional[dict] = None,
    only_currency: bool = False,
) -> str:
    """Generate Excel fare report grouped by international destination."""
    wb = Workbook()
    wb.remove(wb.active)

    airline_names = config.get("airline_names", {}) if config else {}
    city_names = config.get("city_names", {}) if config else {}
    rbd_sort_order = config.get("rbd_sort_order", []) if config else []
    domestic_airports = config.get("domestic_airports", ["DAC"]) if config else ["DAC"]

    cell_locations = {}

    if not only_currency:
        ws = wb.create_sheet(MAIN_SHEET)
        row = 1

        # ── Report header ───────────────────────────────────
        ws.cell(row=row, column=1, value="Fare Comparison Report").font = Font(
            name="Calibri", bold=True, size=16
        )
        row += 1
        ws.cell(
            row=row,
            column=1,
            value=f"Generated: {datetime.now().strftime('%d-%b-%Y %H:%M')}",
        ).font = Font(name="Calibri", size=10, italic=True)
        row += 1

        # Legend
        ws.cell(row=row, column=1, value="Legend:").font = Font(
            name="Calibri", bold=True, size=10
        )
        _legend_cell(ws, row, 2, "1800 ↑ = Increased", INCREASE_FONT, INCREASE_FILL)
        _legend_cell(ws, row, 3, "1800 ↓ = Decreased", DECREASE_FONT, DECREASE_FILL)
        _legend_cell(ws, row, 4, "1800 NEW", NEW_FONT, NEW_FILL)
        _legend_cell(ws, row, 5, "1800 SOLD OUT", SOLD_OUT_FONT, SOLD_OUT_FILL)
        row += 2

        # ── Group routes by (intl_airport, direction) ───────
        # direction: 'outbound' = domestic→intl, 'inbound' = intl→domestic
        sections = _group_by_international(all_route_data, domestic_airports)

        freeze_row = row  # freeze here

        for section_key in sorted(sections.keys()):
            entries = sections[section_key]
            intl_code, direction = section_key
            row, locs = _write_section(
                ws,
                row,
                intl_code,
                direction,
                entries,
                airline_names,
                city_names,
                domestic_airports,
                rbd_sort_order,
                changes,
            )
            cell_locations.update(locs)
            row += 2

        ws.freeze_panes = f"A{freeze_row}"
        _auto_fit_columns(ws)

        # ── Individual Tables sheet (per-airline, side-by-side) ──
        ws_ind = wb.create_sheet("Individual Tables")
        _write_individual_tables_sheet(
            ws_ind,
            all_route_data,
            sections,
            airline_names,
            city_names,
            rbd_sort_order,
            domestic_airports,
            changes,
        )
        _auto_fit_columns(ws_ind)

    # ── Currency Conversion Sheet ───────────────────────
    ws_cur = wb.create_sheet("Currency Conversion")
    _write_currency_sheet(ws_cur, all_route_data, airline_names, city_names)
    _auto_fit_columns(ws_cur)

    # ── YQ/YR/Q Charges Sheet ───────────────────────────
    if not only_currency:
        ws_yq = wb.create_sheet("YQ-YR-Q Charges")
        _write_yq_charges_sheet(
            ws_yq,
            all_route_data,
            _group_by_international(all_route_data, domestic_airports),
            airline_names,
            city_names,
            domestic_airports,
        )
        _auto_fit_columns(ws_yq)

    # ── Tax Breakdowns Sheet ────────────────────────────
    if not only_currency:
        ws_tax = wb.create_sheet("Tax Breakdowns")
        _write_tax_breakdown_sheet(
            ws_tax,
            all_route_data,
            _group_by_international(all_route_data, domestic_airports),
            airline_names,
            city_names,
            domestic_airports,
        )
        _auto_fit_columns(ws_tax)

    # ── Changes Summary sheet ───────────────────────────
    if not only_currency and changes and any(changes.values()):
        ws_ch = wb.create_sheet("Changes Summary")
        _write_changes_summary(
            ws_ch, changes, airline_names, city_names, cell_locations
        )
        _auto_fit_columns(ws_ch)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    wb.save(output_path)
    return output_path


# ── Grouping helper ─────────────────────────────────────
def _group_by_international(all_route_data, domestic_airports):
    """
    Group route_key → route_info by (international_airport, direction).

    Returns:
        { (intl_code, direction): [ (airline, domestic, route_key, route_info), ... ] }
    """
    sections = {}
    for route_key, route_info in all_route_data.items():
        parts = route_key.split("_", 1)
        if len(parts) != 2:
            continue
        airline, route = parts
        if "-" not in route:
            continue
        origin, dest = route.split("-", 1)

        if origin in domestic_airports:
            intl = dest
            direction = "outbound"
            domestic = origin
        elif dest in domestic_airports:
            intl = origin
            direction = "inbound"
            domestic = dest
        else:
            # Neither end is domestic — treat origin as domestic
            intl = dest
            direction = "outbound"
            domestic = origin

        key = (intl, direction)
        if key not in sections:
            sections[key] = []
        sections[key].append((airline, domestic, route_key, route_info))

    return sections


# ── Section writer ──────────────────────────────────────
def _write_section(
    ws,
    start_row,
    intl_code,
    direction,
    entries,
    airline_names,
    city_names,
    domestic_airports,
    rbd_sort_order,
    changes,
):
    """
    Write one section block.  e.g. "→ Doha (DOH)"
    Columns: RBD | [Airline (Origin)] OW | RT | [Airline (Origin)] OW | RT | ...
    """
    row = start_row
    cell_locations = {}

    # Determine currency from first entry
    first_info = entries[0][3] if entries else {}
    currency = first_info.get("currency", "") if isinstance(first_info, dict) else ""

    intl_name = city_names.get(intl_code, intl_code)
    arrow = "→" if direction == "outbound" else "←"
    title = f"{arrow} {intl_name} ({intl_code})"
    if currency:
        title += f"  [{currency}]"

    # Sort entries: by domestic airport order, then airline
    dom_order = {code: i for i, code in enumerate(domestic_airports)}
    entries.sort(key=lambda e: (dom_order.get(e[1], 999), e[0]))

    # Build column list: each entry = (airline, domestic, route_key, info)
    cols_needed = 1 + len(entries) * 2
    ws.cell(row=row, column=1, value=title).font = ROUTE_FONT
    ws.cell(row=row, column=1).fill = ROUTE_FILL
    if cols_needed > 1:
        ws.merge_cells(
            start_row=row, start_column=1, end_row=row, end_column=cols_needed
        )
    row += 1

    # Column headers
    _styled_cell(ws, row, 1, "RBD", HEADER_FONT, HEADER_FILL)
    col = 2
    multi_domestic = len(set(e[1] for e in entries)) > 1
    for airline, domestic, _rk, _ri in entries:
        al_name = airline_names.get(airline, airline)
        dom_name = city_names.get(domestic, domestic)
        label = (
            f"{al_name} ({dom_name})"
            if multi_domestic
            else al_name
        )

        _styled_cell(
            ws,
            row,
            col,
            f"{label} OW",
            HEADER_FONT,
            HEADER_FILL,
            alignment=Alignment(horizontal="center"),
        )
        _styled_cell(
            ws,
            row,
            col + 1,
            f"{label} RT",
            HEADER_FONT,
            HEADER_FILL,
            alignment=Alignment(horizontal="center"),
        )
        col += 2
    row += 1

    # Collect all RBDs across all entries + sold_out from changes
    all_rbds = set()
    for _al, _dom, rk, ri in entries:
        rbd_data = (
            ri.get("rbd_data", ri) if isinstance(ri, dict) and "rbd_data" in ri else ri
        )
        if isinstance(rbd_data, dict):
            all_rbds.update(rbd_data.keys())
    if changes:
        for _al, _dom, rk, _ri in entries:
            for rbd, ci in changes.get(rk, {}).items():
                if ci.get("type") == "sold_out":
                    all_rbds.add(rbd)

    upper_rbds, economy_rbds, unsaleable_rbds = _partition_sorted_rbds(
        entries,
        all_rbds,
        [airline for airline, _domestic, _route_key, _route_info in entries],
        rbd_sort_order,
        changes,
    )
    sorted_rbds = upper_rbds + economy_rbds + unsaleable_rbds

    # Data rows
    for idx, rbd in enumerate(sorted_rbds):
        if upper_rbds and economy_rbds and idx == len(upper_rbds):
            row += 1

        is_unsaleable = rbd in unsaleable_rbds

        ws.cell(row=row, column=1, value=_format_rbd_label(rbd, is_unsaleable)).font = (
            Font(name="Calibri", bold=True, size=11)
            if is_unsaleable
            else Font(name="Calibri", bold=True)
        )

        ws.cell(row=row, column=1).border = THIN_BORDER

        col = 2
        for airline, domestic, route_key, route_info in entries:
            rbd_data = (
                route_info.get("rbd_data", route_info)
                if isinstance(route_info, dict) and "rbd_data" in route_info
                else route_info
            )
            rbd_info = rbd_data.get(rbd) if isinstance(rbd_data, dict) else None

            # Track for hyperlinks
            if route_key not in cell_locations:
                cell_locations[route_key] = {}
            cell_locations[route_key][rbd] = row

            change_info = changes.get(route_key, {}).get(rbd) if changes else None
            change_type = change_info.get("type") if change_info else None

            ow = rbd_info.get("ow_fare") if rbd_info else None
            rt = rbd_info.get("rt_fare") if rbd_info else None
            if change_type == "sold_out":
                ow = change_info.get("old_ow_fare")
                rt = change_info.get("old_rt_fare")

            _write_fare_cell(ws, row, col, ow, change_type)
            _write_fare_cell(ws, row, col + 1, rt, change_type)
            col += 2
        row += 1

    return row, cell_locations


# ── Cell helpers ────────────────────────────────────────
def _fmt_fare(fare):
    """Format fare: 1800.0 → '1,800', None → ''."""
    if fare is None or fare == "":
        return ""
    try:
        return f"{int(round(float(fare))):,}"
    except (ValueError, TypeError):
        return str(fare)


def _write_fare_cell(ws, row, col, fare, change_type):
    """
    Write fare value with change indicator using plain text and font styling.

    Uses simple text concatenation instead of CellRichText to avoid Excel corruption issues.
    """
    cell = ws.cell(row=row, column=col)
    cell.border = THIN_BORDER
    cell.alignment = Alignment(horizontal="right")

    fare_str = _fmt_fare(fare)

    if change_type == "sold_out":
        cell.value = f"{fare_str} SOLD OUT"
        cell.font = SOLD_OUT_FONT
        cell.fill = SOLD_OUT_FILL
    elif change_type == "new":
        cell.value = f"{fare_str} NEW"
        cell.font = NEW_FONT
        cell.fill = NEW_FILL
    elif change_type == "increased" and fare is not None:
        cell.value = f"{fare_str} ↑"
        cell.font = INCREASE_FONT
        cell.fill = INCREASE_FILL
    elif change_type == "decreased" and fare is not None:
        cell.value = f"{fare_str} ↓"
        cell.font = DECREASE_FONT
        cell.fill = DECREASE_FILL
    else:
        cell.value = _fmt_fare(fare) if fare is not None else None


def _styled_cell(ws, row, col, value, font, fill, alignment=None):
    cell = ws.cell(row=row, column=col, value=value)
    cell.font = font
    cell.fill = fill
    cell.border = THIN_BORDER
    if alignment:
        cell.alignment = alignment
    return cell


def _legend_cell(ws, row, col, value, font, fill):
    c = ws.cell(row=row, column=col, value=value)
    c.font = font
    c.fill = fill
    return c


# ── Changes Summary ────────────────────────────────────
def _write_changes_summary(ws, changes, airline_names, city_names, cell_locations):
    row = 1
    ws.cell(row=row, column=1, value="Changes Summary").font = Font(
        name="Calibri", bold=True, size=14
    )
    row += 1
    ws.cell(
        row=row,
        column=1,
        value=f"Generated: {datetime.now().strftime('%d-%b-%Y %H:%M')}",
    ).font = Font(name="Calibri", size=10, italic=True)
    row += 2

    headers = [
        "Route",
        "RBD",
        "Change",
        "Old OW",
        "New OW",
        "Old RT",
        "New RT",
        "Go To",
    ]
    for ci, h in enumerate(headers, 1):
        _styled_cell(ws, row, ci, h, HEADER_FONT, HEADER_FILL)
    row += 1
    ws.freeze_panes = f"A{row}"

    has_changes = False
    for route_key, route_changes in changes.items():
        title = route_key.replace("_", " / ")
        for rbd, change in route_changes.items():
            has_changes = True
            ws.cell(row=row, column=1, value=title).border = THIN_BORDER
            ws.cell(row=row, column=2, value=rbd).border = THIN_BORDER

            ct = change.get("type", "")
            tc = ws.cell(row=row, column=3, value=ct.upper())
            tc.border = THIN_BORDER
            if ct == "new":
                tc.font = NEW_FONT
                tc.fill = NEW_FILL
            elif ct == "increased":
                tc.font = INCREASE_FONT
                tc.fill = INCREASE_FILL
            elif ct == "decreased":
                tc.font = DECREASE_FONT
                tc.fill = DECREASE_FILL
            elif ct == "sold_out":
                tc.font = SOLD_OUT_FONT
                tc.fill = SOLD_OUT_FILL

            ws.cell(row=row, column=4, value=change.get("old_ow_fare")).border = (
                THIN_BORDER
            )
            ws.cell(row=row, column=5, value=change.get("new_ow_fare")).border = (
                THIN_BORDER
            )
            ws.cell(row=row, column=6, value=change.get("old_rt_fare")).border = (
                THIN_BORDER
            )
            ws.cell(row=row, column=7, value=change.get("new_rt_fare")).border = (
                THIN_BORDER
            )

            # Hyperlink
            lc = ws.cell(row=row, column=8)
            lc.border = THIN_BORDER
            target = None
            if route_key in cell_locations and rbd in cell_locations[route_key]:
                target = cell_locations[route_key][rbd]
            if target:
                lc.value = "View →"
                lc.hyperlink = f"#'{MAIN_SHEET}'!A{target}"
                lc.font = Font(
                    name="Calibri", size=10, color="0563C1", underline="single"
                )
            else:
                lc.value = "—"
            row += 1

    if not has_changes:
        ws.cell(row=row, column=1, value="No changes detected.").font = Font(
            name="Calibri", italic=True
        )


def _auto_fit_columns(ws, min_width=10, max_width=30):
    col_widths = [min_width] * (ws.max_column or 0)
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row, values_only=False):
        for cell in row:
            if cell.value:
                idx = cell.column - 1
                col_widths[idx] = max(
                    col_widths[idx], min(len(str(cell.value)) + 2, max_width)
                )
    for ci, width in enumerate(col_widths, 1):
        ws.column_dimensions[get_column_letter(ci)].width = width


# ── Currency Conversion Sheet ───────────────────────────
def _write_currency_sheet(ws, all_route_data, airline_names, city_names):
    """
    Writes a simplified 2-column Currency Conversion sheet exactly
    matching the user's requested layout:
      Current Date
      16-Mar-26
      Currency | Exchange Rate To BDT
      1 KWD    | 400.31968
    """
    # 1. Deduplicate exchange rates. We only need 1 entry per base currency
    rates = {}
    for route_key, info in all_route_data.items():
        fs_taxes = info.get("fs_taxes", {})
        if not fs_taxes or not fs_taxes.get("exchange_rate"):
            continue

        base_cur = fs_taxes.get("base_currency")
        rate = fs_taxes.get("exchange_rate")
        if base_cur and rate:
            # If there's an existing one, just keep the first we find
            if base_cur not in rates:
                rates[base_cur] = rate

    row = 1

    # "Current Date" Header spanning 2 columns
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=2)
    sc1 = ws.cell(row=row, column=1, value="Current Date")
    sc1.font = Font(name="Calibri", bold=True, size=14)
    sc1.alignment = Alignment(horizontal="center")
    sc1.border = THIN_BORDER
    ws.cell(row=row, column=2).border = THIN_BORDER
    row += 1

    # The Date itself spanning 2 columns
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=2)
    dt_str = datetime.now().strftime("%d-%b-%y")
    sc2 = ws.cell(row=row, column=1, value=dt_str)
    sc2.font = Font(name="Calibri", bold=True, size=14)
    sc2.alignment = Alignment(horizontal="center")
    sc2.border = THIN_BORDER
    ws.cell(row=row, column=2).border = THIN_BORDER
    row += 1

    # Table Headers
    h1 = ws.cell(row=row, column=1, value="Currency")
    h1.font = Font(name="Calibri", bold=True, size=14)
    h1.alignment = Alignment(horizontal="center", vertical="center")
    h1.border = THIN_BORDER

    h2 = ws.cell(row=row, column=2, value="Exchange Rate To BDT")
    h2.font = Font(name="Calibri", bold=True, size=14)
    h2.alignment = Alignment(horizontal="center", vertical="center")
    h2.border = THIN_BORDER
    row += 1

    # Data Rows
    for cur, rate in sorted(rates.items()):
        c1 = ws.cell(row=row, column=1, value=f"1 {cur}")
        c1.font = Font(name="Calibri", bold=True, size=14)
        c1.alignment = Alignment(horizontal="center")
        c1.border = THIN_BORDER

        c2 = ws.cell(row=row, column=2, value=rate)
        c2.font = Font(name="Calibri", bold=True, size=14)
        c2.alignment = Alignment(horizontal="center")
        c2.border = THIN_BORDER
        c2.number_format = "0.000000"

        row += 1

    # Auto-fit specifically for this tiny sheet
    ws.column_dimensions["A"].width = 15
    ws.column_dimensions["B"].width = 30


# ── Individual Tables Sheet ─────────────────────────────
def _write_individual_tables_sheet(
    ws,
    all_route_data,
    sections,
    airline_names,
    city_names,
    rbd_sort_order,
    domestic_airports,
    changes,
):
    """
    Write per-airline tables placed side-by-side horizontally.

    Layout:
        8D / MLE-DAC           BS / MLE-DAC           BG / MLE-DAC
        RBD  OW/USD  RT/USD    RBD  OW/USD  RT/USD    RBD  OW/USD  RT/USD
        Y    405     650       J    850     1600       J    2099
        B    180     320       C    700     1300       Y    1417
        ...                    ...                     ...

    Each section (international destination + direction) is a row-group.
    Within each, airlines are placed side-by-side with a 1-column gap.
    """
    current_row = 1

    # Title
    ws.cell(row=current_row, column=1, value="Individual Airline Tables").font = Font(
        name="Calibri", bold=True, size=16
    )
    current_row += 1
    ws.cell(
        row=current_row,
        column=1,
        value=f"Generated: {datetime.now().strftime('%d-%b-%Y %H:%M')}",
    ).font = Font(name="Calibri", size=10, italic=True)
    current_row += 2

    FD_TABLE_WIDTH = 3  # RBD, OW, RT
    TAX_TABLE_WIDTH = 7  # RBD, OW, WithYQ, Gross, RT, WithYQ, Gross
    GAP = 1  # 1 empty column between tables

    for section_key in sorted(sections.keys()):
        entries = sections[section_key]
        intl_code, direction = section_key

        # Sort entries by domestic order then airline
        dom_order = {code: i for i, code in enumerate(domestic_airports)}
        entries.sort(key=lambda e: (dom_order.get(e[1], 999), e[0]))

        intl_name = city_names.get(intl_code, intl_code)
        arrow = "→" if direction == "outbound" else "←"

        # Write section title spanning all tables
        section_title = f"{arrow} {intl_name} ({intl_code})"
        ws.cell(row=current_row, column=1, value=section_title).font = Font(
            name="Calibri", bold=True, size=14
        )
        ws.cell(row=current_row, column=1).fill = ROUTE_FILL
        table_widths = []
        for _airline, _domestic, _route_key, route_info in entries:
            fs_taxes = (
                route_info.get("fs_taxes", {}) if isinstance(route_info, dict) else {}
            )
            table_widths.append(
                TAX_TABLE_WIDTH
                if _has_tax_data_for_individual_table(fs_taxes)
                else FD_TABLE_WIDTH
            )

        total_cols = sum(table_widths) + (GAP * max(len(entries) - 1, 0))
        if total_cols > 1:
            ws.merge_cells(
                start_row=current_row,
                start_column=1,
                end_row=current_row,
                end_column=total_cols,
            )
        current_row += 1

        # Track the tallest table in this row-group
        max_rows_in_group = 0
        table_start_row = current_row

        col_offset = 1
        for (airline, domestic, route_key, route_info), this_table_width in zip(
            entries, table_widths
        ):
            fs_taxes = (
                route_info.get("fs_taxes", {}) if isinstance(route_info, dict) else {}
            )
            yq_charge = fs_taxes.get("yq_charge", 0)
            yr_charge = fs_taxes.get("yr_charge", 0)
            # Q is captured in NUC (= USD) per IATA convention.  ROE scales
            # NUC -> base currency (1.0 for USD-base fares).  exchange_rate
            # scales base -> BDT.
            q_charge_usd = fs_taxes.get("q_charge", 0)
            roe = fs_taxes.get("roe", 1.0) or 1.0
            exch_for_q = fs_taxes.get("exchange_rate", 1.0) or 1.0
            q_charge_bdt = q_charge_usd * roe * exch_for_q
            # yq_total drives the "any charge present?" check below — keep
            # all three charges in it (Q in BDT for the comparison).
            yq_total = yq_charge + yr_charge + q_charge_bdt
            total_tax_val = int(fs_taxes.get("total_taxes", 0))
            has_tax_data = this_table_width == TAX_TABLE_WIDTH

            al_name = airline_names.get(airline, airline)
            dom_name = city_names.get(domestic, domestic)
            currency = (
                route_info.get("currency", "USD")
                if isinstance(route_info, dict)
                else "USD"
            )

            # v1.5.18: gross fare for DAC-origin routes stays in BDT (the
            # local currency of the booking office); routes from other
            # origins use the fare's base currency.  Determine outbound
            # origin from the route_key prefix ("BG_DAC-MLE" → "DAC").
            outbound_origin_for_header = ""
            _route_parts = route_key.split("_", 1)
            if len(_route_parts) == 2 and "-" in _route_parts[1]:
                outbound_origin_for_header = _route_parts[1].split("-", 1)[0]
            gross_currency = "BDT" if outbound_origin_for_header == "DAC" else currency

            rbd_data = (
                route_info.get("rbd_data", route_info)
                if isinstance(route_info, dict) and "rbd_data" in route_info
                else route_info
            )
            if not isinstance(rbd_data, dict):
                rbd_data = {}

            # Include sold_out RBDs from changes
            all_rbds = set(rbd_data.keys())
            if changes and route_key in changes:
                for rbd, ci in changes[route_key].items():
                    if ci.get("type") == "sold_out":
                        all_rbds.add(rbd)

            upper_rbds, economy_rbds, unsaleable_rbds = _partition_sorted_rbds(
                [(airline, domestic, route_key, route_info)],
                all_rbds,
                [airline],
                rbd_sort_order,
                changes,
            )
            sorted_rbds = upper_rbds + economy_rbds + unsaleable_rbds

            # Table title: "BG / DAC-DOH" or "Biman (Dhaka)"
            if direction == "outbound":
                table_title = f"{al_name} / {domestic}-{intl_code}"
            else:
                table_title = f"{al_name} / {intl_code}-{domestic}"

            row = table_start_row

            # Table title
            title_cell = ws.cell(row=row, column=col_offset, value=table_title)
            title_cell.font = Font(name="Calibri", bold=True, size=11)
            ws.merge_cells(
                start_row=row,
                start_column=col_offset,
                end_row=row,
                end_column=col_offset + this_table_width - 1,
            )
            row += 1

            # Tax & Charge Summary Row (User request: Add at the top).
            # YQ/YR are stored in BDT; Q is stored in USD and converted to
            # BDT for this row only — the Individual Tables sheet is the
            # single place where the user wants Q in BDT (everywhere else
            # uses base/fare currency).
            yq_str = (
                f"YQ:{int(yq_charge)} YR:{int(yr_charge)} Q:{int(q_charge_bdt)}"
                if yq_total > 0
                else "None"
            )
            tax_map = fs_taxes.get("tax_breakdown", {})
            tax_breakdown_str = " ".join(
                [
                    f"{k}{int(float(v)) if str(v).replace('.', '', 1).isdigit() else v}"
                    for k, v in tax_map.items()
                ]
            )

            # Use plain text instead of CellRichText to avoid Excel corruption
            summary_text = f"Charges (BDT): {yq_str} | Taxes (BDT): {tax_breakdown_str} | Total Tax (BDT): {total_tax_val}"

            summary_cell = ws.cell(row=row, column=col_offset)
            summary_cell.value = summary_text
            summary_cell.font = Font(name="Calibri", size=9, italic=True)
            ws.merge_cells(
                start_row=row,
                start_column=col_offset,
                end_row=row,
                end_column=col_offset + this_table_width - 1,
            )
            row += 1

            # Column headers
            _styled_cell(ws, row, col_offset, "RBD", HEADER_FONT, HEADER_FILL)
            _styled_cell(
                ws,
                row,
                col_offset + 1,
                f"OW/{currency}",
                HEADER_FONT,
                HEADER_FILL,
                alignment=Alignment(horizontal="center"),
            )

            current_col = col_offset + 2
            if has_tax_data:
                _styled_cell(
                    ws,
                    row,
                    current_col,
                    f"With YQ/OW({currency})",
                    HEADER_FONT,
                    HEADER_FILL,
                    alignment=Alignment(horizontal="center"),
                )
                current_col += 1

                _styled_cell(
                    ws,
                    row,
                    current_col,
                    f"OW/Gross({gross_currency})",
                    HEADER_FONT,
                    HEADER_FILL,
                    alignment=Alignment(horizontal="center"),
                )
                current_col += 1

            _styled_cell(
                ws,
                row,
                current_col,
                f"RT/{currency}",
                HEADER_FONT,
                HEADER_FILL,
                alignment=Alignment(horizontal="center"),
            )
            current_col += 1

            if has_tax_data:
                _styled_cell(
                    ws,
                    row,
                    current_col,
                    f"With YQ/RT({currency})",
                    HEADER_FONT,
                    HEADER_FILL,
                    alignment=Alignment(horizontal="center"),
                )
                current_col += 1

                _styled_cell(
                    ws,
                    row,
                    current_col,
                    f"RT/Gross({gross_currency})",
                    HEADER_FONT,
                    HEADER_FILL,
                    alignment=Alignment(horizontal="center"),
                )
            row += 1

            exchange_rate = fs_taxes.get("exchange_rate", 1.0)
            # v1.5.17: WithYQ now excludes the Q charge (Q is a USD-denominated
            # surcharge captured separately from the fare-construction line and
            # must not be mixed into BDT-summed totals).  Gross-fare columns
            # are now in the fare currency, not BDT.
            yq_ow = float(yq_charge) + float(yr_charge)
            tax_ow = total_tax_val

            inbound_taxes: dict = {}
            outbound_origin = ""
            parts = route_key.split("_", 1)
            if len(parts) == 2 and "-" in parts[1]:
                origin, dest = parts[1].split("-", 1)
                outbound_origin = origin
                inbound_key = f"{parts[0]}_{dest}-{origin}"
                inbound_info = all_route_data.get(inbound_key, {})
                inbound_taxes = inbound_info.get("fs_taxes", {}) or {}

            yq_rt = yq_ow * 2
            # Compensate for origin-sensitive taxes (notably India K3) that
            # appear in isolated one-way scrapes but shouldn't apply to the
            # actual RT journey.
            tax_rt = compute_rt_tax_total(outbound_origin, fs_taxes, inbound_taxes)
            # YQ+YR converted from BDT (equivalent currency) into the fare's
            # base currency.  Q is intentionally NOT added — see yq_ow above.
            yq_ow_in_base = (yq_ow / exchange_rate) if exchange_rate else 0
            yq_rt_in_base = (yq_rt / exchange_rate) if exchange_rate else 0

            # Data rows
            for idx, rbd in enumerate(sorted_rbds):
                if upper_rbds and economy_rbds and idx == len(upper_rbds):
                    row += 1

                rbd_info = rbd_data.get(rbd)
                change_info = changes.get(route_key, {}).get(rbd) if changes else None
                change_type = change_info.get("type") if change_info else None

                ow = rbd_info.get("ow_fare") if rbd_info else None
                rt = rbd_info.get("rt_fare") if rbd_info else None
                if change_type == "sold_out":
                    ow = change_info.get("old_ow_fare")
                    rt = change_info.get("old_rt_fare")

                # Check if this specific table's RBD is unsaleable
                is_unsaleable = rbd in unsaleable_rbds

                ws.cell(
                    row=row,
                    column=col_offset,
                    value=_format_rbd_label(rbd, is_unsaleable),
                ).font = (
                    Font(name="Calibri", bold=True, size=11)
                    if is_unsaleable
                    else Font(name="Calibri", bold=True)
                )

                ws.cell(row=row, column=col_offset).border = THIN_BORDER

                # Base OW
                _write_fare_cell(ws, row, col_offset + 1, ow, change_type)

                current_data_col = col_offset + 2
                if has_tax_data:
                    ow_yq_val = (ow + yq_ow_in_base) if ow else None
                    _write_fare_cell(ws, row, current_data_col, ow_yq_val, None)
                    current_data_col += 1

                    # v1.5.18: DAC-origin routes keep gross in BDT (booking
                    # office's local currency); other origins use the
                    # fare's base currency.  See gross_currency above.
                    if ow and exchange_rate:
                        if gross_currency == "BDT":
                            ow_gross_val = (ow * exchange_rate) + tax_ow
                        else:
                            ow_gross_val = ow + (tax_ow / exchange_rate)
                    else:
                        ow_gross_val = None
                    _write_fare_cell(ws, row, current_data_col, ow_gross_val, None)
                    current_data_col += 1

                # Base RT
                _write_fare_cell(ws, row, current_data_col, rt, change_type)
                current_data_col += 1

                if has_tax_data:
                    rt_yq_val = (rt + yq_rt_in_base) if rt else None
                    _write_fare_cell(ws, row, current_data_col, rt_yq_val, None)
                    current_data_col += 1

                    if rt and exchange_rate:
                        if gross_currency == "BDT":
                            rt_gross_val = (rt * exchange_rate) + tax_rt
                        else:
                            rt_gross_val = rt + (tax_rt / exchange_rate)
                    else:
                        rt_gross_val = None
                    _write_fare_cell(ws, row, current_data_col, rt_gross_val, None)

                row += 1

            table_height = row - table_start_row
            max_rows_in_group = max(max_rows_in_group, table_height)

            col_offset += this_table_width + GAP

        # Move to next section (below the tallest table)
        current_row = table_start_row + max_rows_in_group + 2


# ── Tax Breakdown Sheet ─────────────────────────────────
TAX_HEADER_FILL = PatternFill(
    start_color="1F4E79", end_color="1F4E79", fill_type="solid"
)
TAX_HEADER_FONT = Font(name="Calibri", bold=True, size=10, color="FFFFFF")
TAX_LABEL_FONT = Font(name="Calibri", size=10)
TAX_LABEL_BOLD = Font(name="Calibri", bold=True, size=10)
TAX_TOTAL_FILL = PatternFill(
    start_color="D6E4F0", end_color="D6E4F0", fill_type="solid"
)
TAX_TOTAL_FONT = Font(name="Calibri", bold=True, size=11)
TAX_CHARGE_FILL = PatternFill(
    start_color="FFF2CC", end_color="FFF2CC", fill_type="solid"
)


def _write_tax_breakdown_sheet(
    ws, all_route_data, sections, airline_names, city_names, domestic_airports
):
    """
    Write a dedicated Tax Breakdowns sheet with per-route/airline tables side by side.

    Layout per section (grouped by international destination):
        → Muscat (MCT)
        BG / DAC-MCT          BS / DAC-MCT          UL / DAC-MCT
        Base Currency: USD     Base Currency: USD     ...
        Exchange Rate: 122.71  Exchange Rate: 122.71  ...
        --------------------------
        Tax Code  Amount(BDT)  Tax Code  Amount(BDT)  ...
        YQ        246          YQ        318          ...
        YR        0            YR        100          ...
        BD        500          BD        500          ...
        ...
        ─────────────────────  ─────────────────────
        Total Tax   5375       Total Tax   5900
        Total Amt   27095      Total Amt   29000
    """
    current_row = 1

    # Title
    ws.cell(
        row=current_row, column=1, value="Tax Breakdowns by Route & Airline"
    ).font = Font(name="Calibri", bold=True, size=16)
    current_row += 1
    ws.cell(
        row=current_row,
        column=1,
        value=f"Generated: {datetime.now().strftime('%d-%b-%Y %H:%M')}",
    ).font = Font(name="Calibri", size=10, italic=True)
    current_row += 2

    TABLE_WIDTH = 2  # Tax Code + Amount
    GAP = 1  # 1 empty column between tables

    dom_order = {code: i for i, code in enumerate(domestic_airports)}

    for section_key in sorted(sections.keys()):
        entries = sections[section_key]
        intl_code, direction = section_key

        entries.sort(key=lambda e: (dom_order.get(e[1], 999), e[0]))

        # Filter to entries that actually have tax data
        tax_entries = []
        for airline, domestic, route_key, route_info in entries:
            fs_taxes = (
                route_info.get("fs_taxes", {}) if isinstance(route_info, dict) else {}
            )
            if fs_taxes and (
                fs_taxes.get("total_taxes", 0) > 0
                or fs_taxes.get("yq_charge", 0) > 0
                or fs_taxes.get("tax_breakdown")
            ):
                tax_entries.append((airline, domestic, route_key, route_info))

        if not tax_entries:
            continue

        intl_name = city_names.get(intl_code, intl_code)
        arrow = "→" if direction == "outbound" else "←"

        # Section title
        section_title = f"{arrow} {intl_name} ({intl_code})"
        ws.cell(row=current_row, column=1, value=section_title).font = Font(
            name="Calibri", bold=True, size=14
        )
        ws.cell(row=current_row, column=1).fill = ROUTE_FILL
        total_cols = len(tax_entries) * (TABLE_WIDTH + GAP) - GAP
        if total_cols > 1:
            ws.merge_cells(
                start_row=current_row,
                start_column=1,
                end_row=current_row,
                end_column=total_cols,
            )
        current_row += 1

        table_start_row = current_row
        max_rows_in_group = 0
        col_offset = 1

        for airline, domestic, route_key, route_info in tax_entries:
            fs_taxes = (
                route_info.get("fs_taxes", {}) if isinstance(route_info, dict) else {}
            )
            currency = (
                route_info.get("currency", "USD")
                if isinstance(route_info, dict)
                else "USD"
            )
            al_name = airline_names.get(airline, airline)

            row = table_start_row

            # Table title: "BG / DAC-MCT"
            if direction == "outbound":
                table_title = f"{al_name} / {domestic}-{intl_code}"
            else:
                table_title = f"{al_name} / {intl_code}-{domestic}"

            title_cell = ws.cell(row=row, column=col_offset, value=table_title)
            title_cell.font = Font(name="Calibri", bold=True, size=11)
            ws.merge_cells(
                start_row=row,
                start_column=col_offset,
                end_row=row,
                end_column=col_offset + TABLE_WIDTH - 1,
            )
            row += 1

            # Tax Breakdowns sheet stays in equivalent currency (BDT) —
            # taxes are filed and rendered by Travelport in BDT, and the
            # user wants this sheet to keep its "respective currency".
            # Only Q needs conversion: it's parsed in NUC (USD) per IATA
            # convention but displayed here in BDT.
            base_cur = fs_taxes.get("base_currency", currency)
            equ_cur = fs_taxes.get("equ_currency") or "BDT"
            exch_rate = fs_taxes.get("exchange_rate", 0)
            roe = fs_taxes.get("roe", 1.0) or 1.0

            info_font = Font(name="Calibri", size=9, italic=True)
            ws.cell(
                row=row, column=col_offset, value=f"Base: {base_cur or 'N/A'}"
            ).font = info_font
            ws.cell(
                row=row,
                column=col_offset + 1,
                value=f"Rate: {exch_rate:.4f}" if exch_rate else "Rate: N/A",
            ).font = info_font
            row += 1

            # Column headers
            _styled_cell(
                ws, row, col_offset, "Tax/Charge", TAX_HEADER_FONT, TAX_HEADER_FILL
            )
            _styled_cell(
                ws,
                row,
                col_offset + 1,
                f"Amount ({equ_cur})",
                TAX_HEADER_FONT,
                TAX_HEADER_FILL,
                alignment=Alignment(horizontal="right"),
            )
            row += 1

            # YQ / YR are scraped in BDT — keep raw.  Q is scraped in NUC
            # (USD) and must be converted to BDT for this sheet:
            #   q_bdt = q_usd × roe × exchange_rate
            # For USD-base fares roe == 1 so this collapses to
            # q_usd × exchange_rate.
            yq = float(fs_taxes.get("yq_charge", 0) or 0)
            yr = float(fs_taxes.get("yr_charge", 0) or 0)
            q_usd = float(fs_taxes.get("q_charge", 0) or 0)
            q = q_usd * roe * (exch_rate or 1.0)

            for label, val in [
                ("YQ", yq),
                ("YR", yr),
                ("Q", q),
            ]:
                if val > 0:
                    c1 = ws.cell(row=row, column=col_offset, value=label)
                    c1.font = TAX_LABEL_FONT
                    c1.fill = TAX_CHARGE_FILL
                    c1.border = THIN_BORDER
                    c2 = ws.cell(row=row, column=col_offset + 1, value=val)
                    c2.font = TAX_LABEL_FONT
                    c2.fill = TAX_CHARGE_FILL
                    c2.border = THIN_BORDER
                    c2.number_format = "#,##0.00"
                    c2.alignment = Alignment(horizontal="right")
                    row += 1

            # Separator: Charges subtotal
            charges_total = yq + yr + q
            if charges_total > 0:
                c1 = ws.cell(row=row, column=col_offset, value="Charges Subtotal")
                c1.font = TAX_LABEL_BOLD
                c1.border = THIN_BORDER
                c2 = ws.cell(row=row, column=col_offset + 1, value=charges_total)
                c2.font = TAX_LABEL_BOLD
                c2.border = THIN_BORDER
                c2.number_format = "#,##0.00"
                c2.alignment = Alignment(horizontal="right")
                row += 1

            # Tax codes section
            tax_map = fs_taxes.get("tax_breakdown", {})
            if tax_map:
                # Sub-header for taxes
                ws.cell(row=row, column=col_offset, value="── Taxes ──").font = Font(
                    name="Calibri", bold=True, size=9, italic=True
                )
                row += 1

                for code, amt in sorted(tax_map.items()):
                    # Tax codes (BD, OW, P7, …) are scraped in BDT and
                    # displayed in BDT here — no conversion.
                    c1 = ws.cell(row=row, column=col_offset, value=code)
                    c1.font = TAX_LABEL_FONT
                    c1.border = THIN_BORDER
                    c2 = ws.cell(row=row, column=col_offset + 1, value=float(amt))
                    c2.font = TAX_LABEL_FONT
                    c2.border = THIN_BORDER
                    c2.number_format = "#,##0.00"
                    c2.alignment = Alignment(horizontal="right")
                    row += 1

            # Totals — raw BDT values as scraped, no conversion.
            row += 1  # Blank separator
            total_taxes = float(fs_taxes.get("total_taxes", 0) or 0)
            total_amount = float(fs_taxes.get("total_amount", 0) or 0)

            for label, val in [
                ("Total Taxes", total_taxes),
                ("Total Amount", total_amount),
            ]:
                c1 = ws.cell(row=row, column=col_offset, value=label)
                c1.font = TAX_TOTAL_FONT
                c1.fill = TAX_TOTAL_FILL
                c1.border = THIN_BORDER
                c2 = ws.cell(row=row, column=col_offset + 1, value=val)
                c2.font = TAX_TOTAL_FONT
                c2.fill = TAX_TOTAL_FILL
                c2.border = THIN_BORDER
                c2.number_format = "#,##0.00"
                c2.alignment = Alignment(horizontal="right")
                row += 1

            table_height = row - table_start_row
            max_rows_in_group = max(max_rows_in_group, table_height)
            col_offset += TABLE_WIDTH + GAP

        current_row = table_start_row + max_rows_in_group + 2


# ── YQ/YR/Q Charges Sheet ────────────────────────────────
YQ_HEADER_FILL = PatternFill(
    start_color="375623", end_color="375623", fill_type="solid"
)
YQ_HEADER_FONT = Font(name="Calibri", bold=True, size=10, color="FFFFFF")
YQ_YQ_FILL = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid")
YQ_YR_FILL = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
YQ_Q_FILL = PatternFill(start_color="DEEBF7", end_color="DEEBF7", fill_type="solid")
YQ_SUBTOTAL_FILL = PatternFill(
    start_color="D6E4F0", end_color="D6E4F0", fill_type="solid"
)
YQ_LABEL_FONT = Font(name="Calibri", size=10)
YQ_SUBTOTAL_FONT = Font(name="Calibri", bold=True, size=11)


def _write_yq_charges_sheet(
    ws, all_route_data, sections, airline_names, city_names, domestic_airports
):
    """
    Dedicated sheet showing only YQ / YR / Q (carrier + fuel surcharges) per route/airline.

    Layout per section (grouped by international destination):
        YQ (Carrier)    246      YQ (Carrier)    318
        YR (Carrier)      0      YR (Carrier)    100
        Q  (Fuel)         0      Q  (Fuel)         0
        Total Charges   246      Total Charges   418
    """
    current_row = 1

    ws.cell(
        row=current_row, column=1, value="YQ / YR / Q Surcharges by Route & Airline"
    ).font = Font(name="Calibri", bold=True, size=16)
    current_row += 1
    ws.cell(
        row=current_row,
        column=1,
        value=f"Generated: {datetime.now().strftime('%d-%b-%Y %H:%M')}",
    ).font = Font(name="Calibri", size=10, italic=True)
    current_row += 1
    ws.cell(
        row=current_row,
        column=1,
        value="GDS surcharge codes extracted from FS command output",
    ).font = Font(name="Calibri", size=9, italic=True, color="595959")
    current_row += 2

    TABLE_WIDTH = 2
    GAP = 1

    dom_order = {code: i for i, code in enumerate(domestic_airports)}

    for section_key in sorted(sections.keys()):
        entries = sections[section_key]
        intl_code, direction = section_key

        entries.sort(key=lambda e: (dom_order.get(e[1], 999), e[0]))

        yq_entries = []
        for airline, domestic, route_key, route_info in entries:
            fs_taxes = (
                route_info.get("fs_taxes", {}) if isinstance(route_info, dict) else {}
            )
            if not fs_taxes:
                continue
            yq = fs_taxes.get("yq_charge", 0) or 0
            yr = fs_taxes.get("yr_charge", 0) or 0
            q = fs_taxes.get("q_charge", 0) or 0
            if yq > 0 or yr > 0 or q > 0:
                yq_entries.append((airline, domestic, route_key, route_info))

        if not yq_entries:
            continue

        intl_name = city_names.get(intl_code, intl_code)
        arrow = "→" if direction == "outbound" else "←"
        section_title = f"{arrow} {intl_name} ({intl_code})"

        ws.cell(row=current_row, column=1, value=section_title).font = Font(
            name="Calibri", bold=True, size=14
        )
        ws.cell(row=current_row, column=1).fill = ROUTE_FILL
        total_cols = len(yq_entries) * (TABLE_WIDTH + GAP) - GAP
        if total_cols > 1:
            ws.merge_cells(
                start_row=current_row,
                start_column=1,
                end_row=current_row,
                end_column=total_cols,
            )
        current_row += 1

        table_start_row = current_row
        max_rows_in_group = 0
        col_offset = 1

        for airline, domestic, route_key, route_info in yq_entries:
            fs_taxes = (
                route_info.get("fs_taxes", {}) if isinstance(route_info, dict) else {}
            )
            currency = (
                route_info.get("currency", "USD")
                if isinstance(route_info, dict)
                else "USD"
            )
            al_name = airline_names.get(airline, airline)

            row = table_start_row

            if direction == "outbound":
                table_title = f"{al_name} / {domestic}-{intl_code}"
            else:
                table_title = f"{al_name} / {intl_code}-{domestic}"

            title_cell = ws.cell(row=row, column=col_offset, value=table_title)
            title_cell.font = Font(name="Calibri", bold=True, size=11)
            ws.merge_cells(
                start_row=row,
                start_column=col_offset,
                end_row=row,
                end_column=col_offset + TABLE_WIDTH - 1,
            )
            row += 1

            base_cur = fs_taxes.get("base_currency", currency)
            exch_rate = fs_taxes.get("exchange_rate", 0)
            roe = fs_taxes.get("roe", 1.0) or 1.0
            info_font = Font(name="Calibri", size=9, italic=True)
            ws.cell(
                row=row, column=col_offset, value=f"Base: {base_cur or 'N/A'}"
            ).font = info_font
            ws.cell(
                row=row,
                column=col_offset + 1,
                value=f"Rate: {exch_rate:.4f}" if exch_rate else "Rate: N/A",
            ).font = info_font
            row += 1

            _styled_cell(ws, row, col_offset, "Charge", YQ_HEADER_FONT, YQ_HEADER_FILL)
            _styled_cell(
                ws,
                row,
                col_offset + 1,
                f"Amount ({base_cur or 'USD'})",
                YQ_HEADER_FONT,
                YQ_HEADER_FILL,
                alignment=Alignment(horizontal="right"),
            )
            row += 1

            # YQ / YR are scraped in equivalent currency (BDT) — divide by
            # exchange_rate to get base.  Q is scraped in NUC (= USD per
            # IATA), so multiply by ROE (local-per-NUC) to get base.  ROE
            # defaults to 1.0 for USD-base fares, in which case
            # q_in_base == q_in_usd, the raw value.
            yq = round((fs_taxes.get("yq_charge", 0) or 0) / exch_rate, 2) if exch_rate else (fs_taxes.get("yq_charge", 0) or 0)
            yr = round((fs_taxes.get("yr_charge", 0) or 0) / exch_rate, 2) if exch_rate else (fs_taxes.get("yr_charge", 0) or 0)
            q = round((fs_taxes.get("q_charge", 0) or 0) * roe, 2)

            for label, val, fill in [
                ("YQ", yq, YQ_YQ_FILL),
                ("YR", yr, YQ_YR_FILL),
                ("Q", q, YQ_Q_FILL),
            ]:
                c1 = ws.cell(row=row, column=col_offset, value=label)
                c1.font = YQ_LABEL_FONT
                c1.fill = fill
                c1.border = THIN_BORDER
                c2 = ws.cell(row=row, column=col_offset + 1, value=val)
                c2.font = YQ_LABEL_FONT
                c2.fill = fill
                c2.border = THIN_BORDER
                c2.number_format = "#,##0.00"
                c2.alignment = Alignment(horizontal="right")
                row += 1

            charges_total = yq + yr + q
            c1 = ws.cell(row=row, column=col_offset, value="Total Charges")
            c1.font = YQ_SUBTOTAL_FONT
            c1.fill = YQ_SUBTOTAL_FILL
            c1.border = THIN_BORDER
            c2 = ws.cell(row=row, column=col_offset + 1, value=charges_total)
            c2.font = YQ_SUBTOTAL_FONT
            c2.fill = YQ_SUBTOTAL_FILL
            c2.border = THIN_BORDER
            c2.number_format = "#,##0.00"
            c2.alignment = Alignment(horizontal="right")
            row += 1

            table_height = row - table_start_row
            max_rows_in_group = max(max_rows_in_group, table_height)
            col_offset += TABLE_WIDTH + GAP

        current_row = table_start_row + max_rows_in_group + 2
