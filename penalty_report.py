"""
penalty_report.py - Generate Excel output for fare-basis penalty rules.
"""

from __future__ import annotations

import os
from collections import OrderedDict
from datetime import datetime

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

HEADER_FILL = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
SUBHEADER_FILL = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
HEADER_FONT = Font(color="FFFFFF", bold=True)
SUBHEADER_FONT = Font(color="1F4E78", bold=True)
ROUTE_FILL = PatternFill(start_color="C6E0B4", end_color="C6E0B4", fill_type="solid")
CARRIER_FILL = PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid")
THIN_BORDER = Border(
    left=Side(style="thin"),
    right=Side(style="thin"),
    top=Side(style="thin"),
    bottom=Side(style="thin"),
)
MEDIUM_BORDER = Border(
    left=Side(style="medium"),
    right=Side(style="medium"),
    top=Side(style="medium"),
    bottom=Side(style="medium"),
)


# ── Comparison sheet: bucket classification ────────────────────────────────────

# The six buckets shown in the side-by-side comparison sheet.
COMPARISON_BUCKETS = (
    "reissue_before_24h",
    "reissue_within_24h",
    "reissue_noshow",
    "refund_before_24h",
    "refund_within_24h",
    "refund_noshow",
)

_HOUR_UNITS = {"hour", "minute"}
_WITHIN_QUALIFIERS = {"within", "up_to", "less_than"}


def _classify_rule_bucket(rule: dict) -> str | None:
    """Map a parsed penalty rule into one of the six comparison buckets,
    or None when the rule isn't usable for the comparison (e.g. category
    missing, or timing too vague).

    The category split is exact (CHANGES vs CANCELLATIONS).  The timing
    split is heuristic:
      * subtype == "no_show"          -> *_noshow
      * timing within 24h / less than -> *_within_24h
      * everything else                -> *_before_24h  (default bucket)
    """
    category = rule.get("category")
    if category == "CHANGES":
        prefix = "reissue"
    elif category == "CANCELLATIONS":
        prefix = "refund"
    else:
        return None

    if rule.get("subtype") == "no_show":
        return f"{prefix}_noshow"

    qualifier = rule.get("timing_qualifier") or ""
    unit = rule.get("timing_unit") or ""
    direction = rule.get("timing_direction") or ""
    if (
        qualifier in _WITHIN_QUALIFIERS
        and unit in _HOUR_UNITS
        and direction == "before"
    ):
        return f"{prefix}_within_24h"

    return f"{prefix}_before_24h"


def _format_rule_cell(rule: dict) -> str:
    """Render a rule the way the comparison sheet expects: amount + currency
    when present, otherwise the description. Annotates 'first change free'
    style permitted-rules with the * marker shown in the screenshot."""
    amount = rule.get("amount")
    currency = rule.get("currency")
    description = rule.get("description") or ""

    note_text = (rule.get("note_text") or "").upper()
    first_change_free = (
        "FIRST CHANGE PERMITTED FOC" in note_text
        or "FIRST CHANGE FREE" in note_text
    )

    if amount is not None and currency:
        body = f"{currency} {amount:g}"
    else:
        body = description.strip().rstrip(".")

    return f"{body}*" if first_change_free else body


def _bucket_records_into_comparison_rows(records: list[dict]) -> list[dict]:
    """Group records into the row shape the comparison sheet renders.

    One output row per (route, airline, rbds-key).  rbds-key collapses
    fare bases that share the same set of timing buckets to a single
    row, so a record list with K/B/H sharing all six values produces
    a single row labelled 'K/B/H'.

    Returns rows ordered the way they should appear in the sheet:
    sorted by route, then by airline, then by RBD label.
    """
    # Step 1: classify rules per record.
    per_record: list[dict] = []
    for record in records:
        bucket_values: dict[str, list[str]] = {b: [] for b in COMPARISON_BUCKETS}
        rules = record.get("rules") or []
        # Currency: prefer an explicit record-level value, else fall back to
        # the first rule that carries a currency code.  Penalty records from
        # parse_penalty_text don't set this at the record level today.
        currency = record.get("currency") or ""
        if not currency:
            for rule in rules:
                rc = rule.get("currency")
                if rc:
                    currency = rc
                    break
        for rule in rules:
            bucket = _classify_rule_bucket(rule)
            if not bucket:
                continue
            text = _format_rule_cell(rule)
            if text and text not in bucket_values[bucket]:
                bucket_values[bucket].append(text)
        per_record.append(
            {
                "airline": record.get("airline") or "",
                "route": record.get("route") or "",
                "rbd": record.get("rbd") or "",
                "currency": currency,
                "buckets": {b: " / ".join(v) for b, v in bucket_values.items()},
            }
        )

    # Step 2: group records that share identical bucket values under one
    # airline so multiple fare bases collapse into a single RBDs row.
    grouped: "OrderedDict[tuple[str, str, tuple[tuple[str, str], ...]], dict]" = OrderedDict()
    for entry in per_record:
        bucket_signature = tuple(sorted(entry["buckets"].items()))
        key = (entry["route"], entry["airline"], bucket_signature)
        slot = grouped.get(key)
        if slot is None:
            slot = {
                "route": entry["route"],
                "airline": entry["airline"],
                "rbds": [],
                "currency": entry["currency"],
                "buckets": entry["buckets"],
            }
            grouped[key] = slot
        rbd = entry["rbd"]
        if rbd and rbd not in slot["rbds"]:
            slot["rbds"].append(rbd)

    rows: list[dict] = []
    for slot in grouped.values():
        rbds_label = "/".join(slot["rbds"]) if slot["rbds"] else "ALL"
        rows.append(
            {
                "route": slot["route"],
                "airline": slot["airline"],
                "rbds": rbds_label,
                "currency": slot["currency"],
                "buckets": slot["buckets"],
            }
        )

    rows.sort(key=lambda r: (r["route"], r["airline"], r["rbds"]))
    return rows


def _route_label(route: str, currency: str) -> str:
    """Render the route header as it appears in the screenshot: 'DAC-CCU (USD)'."""
    return f"{route} ({currency})" if currency else route or ""


def _write_comparison_sheet(ws, records: list[dict]) -> None:
    """Write the side-by-side reissue/refund comparison sheet.

    Layout (1-based columns):
        A: Route+currency  (merged across rows of the same route block)
        B: Carrier         (merged across rows of the same airline)
        C: RBDs
        D-F: Re-issue (Before 24 Hours | Within 24 Hours | NOSHOW)
        G: visual gap
        H-J: Refund (Before 24 Hours | Within 24 Hours | NOSHOW)

    A two-row header is used: Row 1 spans Re-issue / Refund banners,
    Row 2 carries the per-bucket sub-headers.  Merged cells anchor at
    the top-left of each merged block so openpyxl writes correctly.
    """
    # Top banner row (matches the screenshot's "Reissue and Refund Charges").
    ws.cell(row=1, column=1, value="Reissue and Refund Charges")
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=10)
    banner = ws.cell(row=1, column=1)
    banner.fill = HEADER_FILL
    banner.font = HEADER_FONT
    banner.alignment = Alignment(horizontal="center", vertical="center")
    banner.border = THIN_BORDER

    # Row 2: section banners.
    headers_section = [
        (1, 1, "", None),
        (1, 2, "", None),
        (1, 3, "", None),
        (3, 4, "Re-issue", HEADER_FILL),
        (1, 7, "", None),
        (3, 8, "Refund", HEADER_FILL),
    ]
    for span, col, text, fill in headers_section:
        ws.cell(row=2, column=col, value=text)
        if span > 1:
            ws.merge_cells(
                start_row=2, start_column=col, end_row=2, end_column=col + span - 1
            )
        cell = ws.cell(row=2, column=col)
        if fill is not None:
            cell.fill = fill
            cell.font = HEADER_FONT
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = THIN_BORDER

    # Row 3: per-column sub-headers.
    sub_headers = [
        (1, "Route"),
        (2, "Carrier"),
        (3, "RBDs"),
        (4, "Before 24 Hours"),
        (5, "Within 24 Hours"),
        (6, "NOSHOW"),
        (7, ""),
        (8, "Before 24 Hours"),
        (9, "Within 24 Hours"),
        (10, "NOSHOW"),
    ]
    for col, text in sub_headers:
        cell = ws.cell(row=3, column=col, value=text)
        cell.fill = SUBHEADER_FILL
        cell.font = SUBHEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = THIN_BORDER

    rows = _bucket_records_into_comparison_rows(records)
    if not rows:
        ws.cell(row=4, column=1, value="No penalty data available.")
        ws.merge_cells(start_row=4, start_column=1, end_row=4, end_column=10)
        return

    next_row = 4
    last_route_key: str | None = None
    last_airline_key: tuple[str, str] | None = None
    route_block_start: int = next_row
    airline_block_start: int = next_row

    for row in rows:
        route_key = row["route"]
        airline_key = (row["route"], row["airline"])

        if route_key != last_route_key:
            if last_route_key is not None and route_block_start < next_row - 1:
                # Merge the prior route block's column-A cells.
                ws.merge_cells(
                    start_row=route_block_start,
                    start_column=1,
                    end_row=next_row - 1,
                    end_column=1,
                )
            route_block_start = next_row
            last_route_key = route_key

        if airline_key != last_airline_key:
            if last_airline_key is not None and airline_block_start < next_row - 1:
                ws.merge_cells(
                    start_row=airline_block_start,
                    start_column=2,
                    end_row=next_row - 1,
                    end_column=2,
                )
            airline_block_start = next_row
            last_airline_key = airline_key

        cells = [
            (1, _route_label(row["route"], row["currency"]), ROUTE_FILL),
            (2, row["airline"], CARRIER_FILL),
            (3, row["rbds"], None),
            (4, row["buckets"].get("reissue_before_24h", ""), None),
            (5, row["buckets"].get("reissue_within_24h", ""), None),
            (6, row["buckets"].get("reissue_noshow", ""), None),
            (7, "", None),
            (8, row["buckets"].get("refund_before_24h", ""), None),
            (9, row["buckets"].get("refund_within_24h", ""), None),
            (10, row["buckets"].get("refund_noshow", ""), None),
        ]
        for col, value, fill in cells:
            cell = ws.cell(row=next_row, column=col, value=value)
            if fill is not None:
                cell.fill = fill
            cell.alignment = Alignment(
                horizontal="center", vertical="center", wrap_text=True
            )
            cell.border = THIN_BORDER

        next_row += 1

    # Merge the trailing route / airline blocks.
    if last_airline_key is not None and airline_block_start < next_row - 1:
        ws.merge_cells(
            start_row=airline_block_start,
            start_column=2,
            end_row=next_row - 1,
            end_column=2,
        )
    if last_route_key is not None and route_block_start < next_row - 1:
        ws.merge_cells(
            start_row=route_block_start,
            start_column=1,
            end_row=next_row - 1,
            end_column=1,
        )

    # Footer note (matches the screenshot's '* First change free').
    footer_row = next_row + 1
    footer_cell = ws.cell(
        row=footer_row, column=1, value="* First change free"
    )
    ws.merge_cells(
        start_row=footer_row, start_column=1, end_row=footer_row, end_column=10
    )
    footer_cell.fill = PatternFill(start_color="FFFF00", end_color="FFFF00", fill_type="solid")
    footer_cell.alignment = Alignment(horizontal="center", vertical="center")
    footer_cell.font = Font(italic=True, bold=True)

    # Column widths roughly matching the screenshot.
    widths = {1: 16, 2: 6, 3: 14, 4: 22, 5: 22, 6: 24, 7: 3, 8: 22, 9: 22, 10: 24}
    for col, width in widths.items():
        ws.column_dimensions[get_column_letter(col)].width = width
    ws.freeze_panes = "D4"


def _summarize_rules(record: dict, category: str) -> str:
    snippets = []
    for rule in record.get("rules", []):
        if rule.get("category") != category:
            continue

        timing_suffix = f" [{rule['timing_text']}]" if rule.get("timing_text") else ""
        if rule.get("amount") is not None and rule.get("currency"):
            snippets.append(
                f"{rule['criteria_text'] or 'General'}: {rule['currency']} {rule['amount']:.2f} {rule['description']}{timing_suffix}"
            )
        else:
            snippets.append(
                f"{rule['criteria_text'] or 'General'}: {rule['description']}{timing_suffix}"
            )

    return "\n".join(snippets)


def _style_header_row(ws, headers):
    ws.append(headers)
    for column in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=column)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.border = THIN_BORDER
        cell.alignment = Alignment(horizontal="center", vertical="center")


def _auto_fit(ws):
    for column_cells in ws.columns:
        letter = get_column_letter(column_cells[0].column)
        max_width = max(len(str(cell.value or "")) for cell in column_cells)
        ws.column_dimensions[letter].width = min(max(max_width + 2, 12), 55)


def generate_penalty_report(records: list[dict], output_path: str) -> str:
    wb = openpyxl.Workbook()
    try:
        if "Sheet" in wb.sheetnames:
            wb.remove(wb["Sheet"])

        ws_comparison = wb.create_sheet("Comparison")
        ws_summary = wb.create_sheet("Penalty Summary")
        ws_details = wb.create_sheet("Penalty Details")
        ws_raw = wb.create_sheet("Raw Captures")

        _write_comparison_sheet(ws_comparison, records or [])

        _style_header_row(
            ws_summary,
            [
                "Airline",
                "Route",
                "RBD",
                "Fare Basis",
                "Journey",
                "Fare Amount",
                "Change Summary",
                "Cancellation Summary",
                "Rule Count",
            ],
        )

        _style_header_row(
            ws_details,
            [
                "Airline",
                "Route",
                "RBD",
                "Fare Basis",
                "Journey",
                "Fare Amount",
                "Category",
                "Subtype",
                "Criteria",
                "Timing Text",
                "Timing Qualifier",
                "Timing Value",
                "Timing Unit",
                "Timing Direction",
                "Timing Reference",
                "Amount",
                "Currency",
                "Status",
                "Description",
                "Notes",
            ],
        )

        _style_header_row(
            ws_raw,
            ["Airline", "Route", "RBD", "Fare Basis", "Journey", "Raw Penalty Text"],
        )

        sorted_records = sorted(
            records,
            key=lambda item: (
                item.get("airline") or "",
                item.get("route") or "",
                item.get("rbd") or "",
                item.get("fare_basis") or "",
            ),
        )

        for record in sorted_records:
            ws_summary.append(
                [
                    record.get("airline"),
                    record.get("route"),
                    record.get("rbd"),
                    record.get("fare_basis"),
                    record.get("journey_type"),
                    record.get("fare_amount"),
                    _summarize_rules(record, "CHANGES"),
                    _summarize_rules(record, "CANCELLATIONS"),
                    len(record.get("rules", [])),
                ]
            )

            for rule in record.get("rules", []):
                ws_details.append(
                    [
                        record.get("airline"),
                        record.get("route"),
                        record.get("rbd"),
                        record.get("fare_basis"),
                        record.get("journey_type"),
                        record.get("fare_amount"),
                        rule.get("category"),
                        rule.get("subtype"),
                        rule.get("criteria_text"),
                        rule.get("timing_text"),
                        rule.get("timing_qualifier"),
                        rule.get("timing_value"),
                        rule.get("timing_unit"),
                        rule.get("timing_direction"),
                        rule.get("timing_reference"),
                        rule.get("amount"),
                        rule.get("currency"),
                        rule.get("status"),
                        rule.get("description"),
                        rule.get("note_text"),
                    ]
                )

            ws_raw.append(
                [
                    record.get("airline"),
                    record.get("route"),
                    record.get("rbd"),
                    record.get("fare_basis"),
                    record.get("journey_type"),
                    record.get("raw_penalty_text"),
                ]
            )

        for ws in (ws_summary, ws_details, ws_raw):
            ws.freeze_panes = "A2"
            for row in ws.iter_rows(min_row=2):
                for cell in row:
                    cell.border = THIN_BORDER
                    cell.alignment = Alignment(vertical="top", wrap_text=True)
            _auto_fit(ws)

        ws_summary["K1"] = f"Generated: {datetime.now().strftime('%d-%b-%Y %H:%M')}"

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        wb.save(output_path)
        return output_path
    finally:
        wb.close()
