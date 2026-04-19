import os
import logging
from collections import defaultdict
from datetime import datetime

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

logger = logging.getLogger("travelport.tax_report")

# ── Styles ───────────────────────────────────────────────
HEADER_FILL = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
HEADER_FONT = Font(color="FFFFFF", bold=True)

THIN_BORDER = Border(
    left=Side(style="thin"),
    right=Side(style="thin"),
    top=Side(style="thin"),
    bottom=Side(style="thin"),
)

EXPIRED_FILL = PatternFill(start_color="E7E6E6", end_color="E7E6E6", fill_type="solid")
CURRENT_FILL = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid")
FUTURE_FILL = PatternFill(start_color="DDEBF7", end_color="DDEBF7", fill_type="solid")

# ─────────────────────────────────────────────────────────


def generate_tax_report(
    data: dict, output_path: str, changes: dict = None, config: dict = None
) -> str:
    """
    Generate a 3-sheet Excel report for tax data:
    1. Tax Summary
    2. Detailed Rates
    3. Changes Summary
    """
    wb = openpyxl.Workbook()

    # Remove default sheet
    if "Sheet" in wb.sheetnames:
        wb.remove(wb["Sheet"])

    ws_summary = wb.create_sheet("Tax Summary")
    ws_details = wb.create_sheet("Detailed Rates")

    _build_summary_sheet(ws_summary, data, config)
    _build_details_sheet(ws_details, data, config)

    if changes and any(changes.values()):
        ws_changes = wb.create_sheet("Changes")
        _build_changes_sheet(ws_changes, changes, data)

    # Save
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    wb.save(output_path)
    return output_path


def _build_summary_sheet(ws, data, config):
    """Build the summary table — one row per rate with time-range conditions."""
    headers = [
        "Airport",
        "Country",
        "Tax Code",
        "Tax Name",
        "Terminal / Category",
        "Condition / Time Range",
        "Currency",
        "Amount",
        "Status",
    ]

    ws.append(headers)
    for col in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.border = THIN_BORDER
        cell.alignment = Alignment(horizontal="center")

    row_idx = 2

    # Iterate airports
    for airport_code, airport_data in data.items():
        country_name = ""
        if config and "tax_airports" in config:
            country_name = config["tax_airports"].get(airport_code, {}).get("name", "")
        if not country_name:
            country_name = airport_data.get("_country", "")

        for tax_type in airport_data.get("taxes", []):
            code = tax_type.get("code", "")
            name = tax_type.get("name", "")

            for section in tax_type.get("sections", []):
                category = section.get("category", "")
                subcategory = section.get("subcategory", "")
                terminals = f"{category} {subcategory}".strip()

                for rate in section.get("rates", []):
                    condition = rate.get("condition", "")
                    currency = rate.get("currency", "")
                    amount = rate.get("amount", "")
                    status = rate.get("status", "")

                    status_text = status.title() if status else ""
                    if status == "current":
                        status_text = "Current ●"

                    ws.append(
                        [
                            airport_code,
                            country_name,
                            code,
                            name,
                            terminals,
                            condition,
                            currency,
                            amount if amount != "" else "—",
                            status_text,
                        ]
                    )

                    # Apply status coloring
                    fill = None
                    if status == "current":
                        fill = CURRENT_FILL
                    elif status == "expired":
                        fill = EXPIRED_FILL
                    elif status == "future":
                        fill = FUTURE_FILL

                    for col in range(1, len(headers) + 1):
                        cell = ws.cell(row=row_idx, column=col)
                        cell.border = THIN_BORDER
                        if fill and col in (8, 9):  # Amount and Status columns
                            cell.fill = fill

                    # Format amount as number
                    amt_cell = ws.cell(row=row_idx, column=8)
                    if isinstance(amount, (int, float)):
                        amt_cell.number_format = "#,##0.00"

                    row_idx += 1

                # If section has no rates, show one row with dashes
                if not section.get("rates", []):
                    ws.append(
                        [
                            airport_code,
                            country_name,
                            code,
                            name,
                            terminals,
                            "—",
                            "—",
                            "—",
                            "—",
                        ]
                    )
                    for col in range(1, len(headers) + 1):
                        ws.cell(row=row_idx, column=col).border = THIN_BORDER
                    row_idx += 1

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:I{row_idx-1}"

    # Column widths
    widths = [10, 15, 10, 30, 40, 40, 10, 12, 12]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w


def _build_details_sheet(ws, data, config):
    """Build the full timeline sheet for all taxes."""
    row_idx = 1

    for airport_code, airport_data in data.items():
        country_name = ""
        if config and "tax_airports" in config:
            country_name = config["tax_airports"].get(airport_code, {}).get("name", "")
        if not country_name:
            country_name = airport_data.get("_country", "")

        for tax_type in airport_data.get("taxes", []):
            # Title block
            code = tax_type.get("code", "")
            name = tax_type.get("name", "")
            title = f"{country_name} ({airport_code}) — {name} ({code})"

            ws.cell(row=row_idx, column=1, value=title).font = Font(bold=True, size=12)
            row_idx += 1

            headers = ["Condition", "Currency", "Amount", "Status"]
            for col, text in enumerate(headers, 1):
                cell = ws.cell(row=row_idx, column=col, value=text)
                cell.fill = HEADER_FILL
                cell.font = HEADER_FONT
                cell.border = THIN_BORDER
            row_idx += 1

            for section in tax_type.get("sections", []):
                # Category row
                category = section.get("category", "")
                subcategory = section.get("subcategory", "")
                terminals = f"{category} {subcategory}".strip()

                cat_cell = ws.cell(row=row_idx, column=1, value=terminals)
                cat_cell.font = Font(bold=True)
                ws.merge_cells(
                    start_row=row_idx, start_column=1, end_row=row_idx, end_column=4
                )
                for c in range(1, 5):
                    ws.cell(row=row_idx, column=c).border = THIN_BORDER
                row_idx += 1

                # Rates
                for rate in section.get("rates", []):
                    status = rate.get("status", "")

                    status_text = status.title()
                    fill = None
                    if status == "current":
                        status_text = "Current ●"
                        fill = CURRENT_FILL
                    elif status == "expired":
                        fill = EXPIRED_FILL
                    elif status == "future":
                        fill = FUTURE_FILL

                    ws.cell(
                        row=row_idx, column=1, value=rate.get("condition", "")
                    ).border = THIN_BORDER
                    ws.cell(
                        row=row_idx, column=2, value=rate.get("currency", "")
                    ).border = THIN_BORDER

                    amt_cell = ws.cell(
                        row=row_idx, column=3, value=rate.get("amount", "")
                    )
                    amt_cell.border = THIN_BORDER
                    amt_cell.number_format = "#,##0.00"

                    st_cell = ws.cell(row=row_idx, column=4, value=status_text)
                    st_cell.border = THIN_BORDER
                    if fill:
                        st_cell.fill = fill

                    row_idx += 1

            row_idx += 2  # Gap between taxes

    # Widths
    ws.column_dimensions["A"].width = 50
    ws.column_dimensions["B"].width = 10
    ws.column_dimensions["C"].width = 15
    ws.column_dimensions["D"].width = 15


def _build_changes_sheet(ws, changes, data):
    """
    Build the tax changes summary sheet.

    Shows all changes (new, removed, amount_changed) for each airport/tax combination.
    """
    # Header
    row = 1
    ws.cell(row=row, column=1, value="Tax Changes Summary").font = Font(
        bold=True, size=14
    )
    row += 1
    ws.cell(
        row=row,
        column=1,
        value=f"Generated: {datetime.now().strftime('%d-%b-%Y %H:%M')}",
    ).font = Font(size=10, italic=True)
    row += 2

    headers = [
        "Airport",
        "Tax Code",
        "Tax Name",
        "Section",
        "Condition",
        "Change Type",
        "Old Amount",
        "New Amount",
        "Currency",
        "Status",
    ]

    for col, text in enumerate(headers, 1):
        cell = ws.cell(row=row, column=col, value=text)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.border = THIN_BORDER
        cell.alignment = Alignment(horizontal="center")
    row += 1
    ws.freeze_panes = f"A{row}"

    # Change type fills
    NEW_FILL = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
    REMOVED_FILL = PatternFill(
        start_color="FFC7CE", end_color="FFC7CE", fill_type="solid"
    )
    CHANGED_FILL = PatternFill(
        start_color="FFEB9C", end_color="FFEB9C", fill_type="solid"
    )

    has_changes = False

    for airport_code, airport_changes in changes.items():
        # Get tax names from data
        airport_data = data.get(airport_code, {})
        tax_types = airport_data.get("taxes", [])
        tax_name_lookup = {
            t.get("code"): t.get("name") for t in tax_types if t.get("code")
        }

        for tax_code, tax_changes in airport_changes.items():
            tax_name = tax_name_lookup.get(tax_code, "")

            for change in tax_changes:
                has_changes = True

                change_type = change.get("type", "").upper()
                section = change.get("section", "")
                condition = change.get("condition", "")
                old_amt = change.get("old_amount", "")
                new_amt = change.get("new_amount", "")
                currency = change.get("currency", "")
                status = change.get("status", "")

                # Write data
                ws.cell(row=row, column=1, value=airport_code).border = THIN_BORDER
                ws.cell(row=row, column=2, value=tax_code).border = THIN_BORDER
                ws.cell(row=row, column=3, value=tax_name).border = THIN_BORDER
                ws.cell(row=row, column=4, value=section).border = THIN_BORDER
                ws.cell(row=row, column=5, value=condition).border = THIN_BORDER

                # Change type with color
                ct_cell = ws.cell(row=row, column=6, value=change_type)
                ct_cell.border = THIN_BORDER
                ct_cell.font = Font(bold=True)
                if change_type == "NEW":
                    ct_cell.fill = NEW_FILL
                elif change_type == "REMOVED":
                    ct_cell.fill = REMOVED_FILL
                elif change_type == "AMOUNT_CHANGED":
                    ct_cell.fill = CHANGED_FILL

                # Old and new amounts
                old_cell = ws.cell(row=row, column=7, value=old_amt if old_amt else "—")
                old_cell.border = THIN_BORDER
                if isinstance(old_amt, (int, float)):
                    old_cell.number_format = "#,##0.00"

                new_cell = ws.cell(row=row, column=8, value=new_amt if new_amt else "—")
                new_cell.border = THIN_BORDER
                if isinstance(new_amt, (int, float)):
                    new_cell.number_format = "#,##0.00"

                ws.cell(row=row, column=9, value=currency).border = THIN_BORDER
                ws.cell(row=row, column=10, value=status.title()).border = THIN_BORDER

                row += 1

    if not has_changes:
        ws.cell(row=row, column=1, value="No changes detected.").font = Font(
            italic=True
        )

    # Column widths
    widths = [10, 10, 30, 40, 40, 15, 12, 12, 10, 12]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
