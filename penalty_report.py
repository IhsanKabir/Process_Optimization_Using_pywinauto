"""
penalty_report.py - Generate Excel output for fare-basis penalty rules.
"""

from __future__ import annotations

import os
from datetime import datetime

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

HEADER_FILL = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
HEADER_FONT = Font(color="FFFFFF", bold=True)
THIN_BORDER = Border(
    left=Side(style="thin"),
    right=Side(style="thin"),
    top=Side(style="thin"),
    bottom=Side(style="thin"),
)


def _summarize_rules(record: dict, category: str) -> str:
    snippets = []
    for rule in record.get("rules", []):
        if rule.get("category") != category:
            continue

        timing_suffix = (
            f" [{rule['timing_text']}]"
            if rule.get("timing_text")
            else ""
        )
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

        ws_summary = wb.create_sheet("Penalty Summary")
        ws_details = wb.create_sheet("Penalty Details")
        ws_raw = wb.create_sheet("Raw Captures")

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
