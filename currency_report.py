"""
currency_report.py - Standalone Currency Rate report.

Emits a dedicated xlsx with:
    Current Date block  | Previous Date block | Zenith Value
    Currency | BDT rate | Currency | BDT rate | Zenith

Rules:
- Sorted descending by current BDT rate.
- Current-day cells highlighted (cyan fill) only where value differs from previous.
- For USD, a "(DD-MMM-YY)" suffix is rendered next to the current value, where the
  date is the most recent date USD ever changed (tracked in usd_tracker.json).
  The suffix text is colored red; the USD value itself is unhighlighted unless
  the rate changed from previous day.
- Zenith Value = 1 / current_rate.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from currency_archive import (
    RateSnapshot,
    UsdTracker,
    latest_prior_snapshot,
    load_usd_tracker,
    save_snapshot,
    update_usd_tracker,
)

logger = logging.getLogger("travelport.currency_report")

# ── Styles ──────────────────────────────────────────────────────────────────
THIN_BORDER = Border(
    left=Side(style="thin"),
    right=Side(style="thin"),
    top=Side(style="thin"),
    bottom=Side(style="thin"),
)
HEADER_FONT = Font(name="Calibri", bold=True, size=13)
DATE_FONT = Font(name="Calibri", bold=True, size=12)
TABLE_HEADER_FONT = Font(name="Calibri", bold=True, size=12)
BODY_FONT = Font(name="Calibri", size=11)
ZENITH_HEADER_FONT = Font(name="Calibri", bold=True, size=12, color="B8860B")
USD_DATE_FONT_COLOR = "B80000"  # red used only for the USD bracket

CHANGED_FILL = PatternFill(start_color="C6E7F5", end_color="C6E7F5", fill_type="solid")
CENTER = Alignment(horizontal="center", vertical="center")
RIGHT = Alignment(horizontal="right", vertical="center")


@dataclass(frozen=True)
class CurrencyReportResult:
    path: str
    run_date: date
    previous_date: Optional[date]
    usd_tracker: UsdTracker


# ── Public API ──────────────────────────────────────────────────────────────


def generate_currency_report(
    current_rates: dict,
    output_path: str,
    run_date: Optional[date] = None,
    persist: bool = True,
) -> CurrencyReportResult:
    """Build the Currency Rate xlsx.

    current_rates : {"USD": 122.94, "KWD": 398.42704, ...}  (BDT per 1 unit)
    output_path   : absolute path for the xlsx (overwritten on save).
    run_date      : effective date for the "Current Date" column; defaults to today.
    persist       : when True, saves today's snapshot and updates the USD tracker.
    """
    run_date = run_date or datetime.now().date()
    normalized = {str(k).upper(): float(v) for k, v in current_rates.items() if v}

    if persist:
        save_snapshot(RateSnapshot(snapshot_date=run_date, rates=normalized, source="live"))

    prior = latest_prior_snapshot(run_date)
    prev_rates = prior.rates if prior else {}

    usd_rate = normalized.get("USD")
    if persist and usd_rate:
        tracker = update_usd_tracker(usd_rate, run_date)
    else:
        tracker = load_usd_tracker() or UsdTracker(
            rate=usd_rate or 0.0, last_changed_date=run_date
        )

    wb = Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("Currency Rate")
    _write_sheet(
        ws,
        current_rates=normalized,
        previous_rates=prev_rates,
        run_date=run_date,
        previous_date=prior.snapshot_date if prior else None,
        usd_tracker=tracker,
    )

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    wb.save(output_path)
    return CurrencyReportResult(
        path=output_path,
        run_date=run_date,
        previous_date=prior.snapshot_date if prior else None,
        usd_tracker=tracker,
    )


# ── Worksheet layout ────────────────────────────────────────────────────────


def _write_sheet(
    ws,
    current_rates: dict,
    previous_rates: dict,
    run_date: date,
    previous_date: Optional[date],
    usd_tracker: UsdTracker,
) -> None:
    # Column map (single Currency column, no duplicate labels, no blank spacer):
    #   A: Currency       B: Current Rate       C: Previous Rate       D: Zenith Value
    currencies = sorted(
        current_rates.keys(), key=lambda c: current_rates[c], reverse=True
    )

    # Row 1 — group headers. Currency and Zenith span the date sub-row.
    ws.merge_cells(start_row=1, start_column=1, end_row=2, end_column=1)
    a1 = ws.cell(row=1, column=1, value="Currency")
    a1.font = HEADER_FONT
    a1.alignment = CENTER
    a1.border = THIN_BORDER
    ws.cell(row=2, column=1).border = THIN_BORDER

    b1 = ws.cell(row=1, column=2, value="Current Date")
    b1.font = HEADER_FONT
    b1.alignment = CENTER
    b1.border = THIN_BORDER

    c1 = ws.cell(row=1, column=3, value="Previous Date")
    c1.font = HEADER_FONT
    c1.alignment = CENTER
    c1.border = THIN_BORDER

    ws.merge_cells(start_row=1, start_column=4, end_row=2, end_column=4)
    d1 = ws.cell(row=1, column=4, value="Zenith Value")
    d1.font = ZENITH_HEADER_FONT
    d1.alignment = CENTER
    d1.border = THIN_BORDER
    ws.cell(row=2, column=4).border = THIN_BORDER

    # Row 2 — date strings under the Current / Previous group headers.
    b2 = ws.cell(row=2, column=2, value=run_date.strftime("%d-%b-%y"))
    b2.font = DATE_FONT
    b2.alignment = CENTER
    b2.border = THIN_BORDER

    prev_label = previous_date.strftime("%d-%b-%y") if previous_date else "—"
    c2 = ws.cell(row=2, column=3, value=prev_label)
    c2.font = DATE_FONT
    c2.alignment = CENTER
    c2.border = THIN_BORDER

    # Row 3 — rate sub-header ("Exchange Rate To BDT") under B and C only.
    sub_a = ws.cell(row=3, column=1, value="")
    sub_a.border = THIN_BORDER

    sub_b = ws.cell(row=3, column=2, value="Exchange Rate To BDT")
    sub_b.font = TABLE_HEADER_FONT
    sub_b.alignment = CENTER
    sub_b.border = THIN_BORDER

    sub_c = ws.cell(row=3, column=3, value="Exchange Rate To BDT")
    sub_c.font = TABLE_HEADER_FONT
    sub_c.alignment = CENTER
    sub_c.border = THIN_BORDER

    sub_d = ws.cell(row=3, column=4, value="")
    sub_d.border = THIN_BORDER

    # Data rows
    row = 4
    for cur in currencies:
        cur_rate = current_rates[cur]
        prev_rate = previous_rates.get(cur)

        # Currency label (single column)
        lbl = ws.cell(row=row, column=1, value=f"1 {cur}")
        lbl.font = BODY_FONT
        lbl.alignment = CENTER
        lbl.border = THIN_BORDER

        # Current rate
        value_cell = ws.cell(row=row, column=2)
        value_cell.border = THIN_BORDER
        value_cell.alignment = CENTER

        is_changed = prev_rate is None or not _rates_equal(cur_rate, prev_rate)
        if is_changed:
            lbl.fill = CHANGED_FILL
            value_cell.fill = CHANGED_FILL

        if cur == "USD":
            _write_usd_current_cell(value_cell, cur_rate, usd_tracker, run_date)
        else:
            value_cell.value = cur_rate
            value_cell.font = BODY_FONT
            value_cell.number_format = "0.000000"

        # Previous rate
        prev_value_cell = ws.cell(row=row, column=3)
        prev_value_cell.border = THIN_BORDER
        prev_value_cell.alignment = CENTER
        prev_value_cell.font = BODY_FONT
        if prev_rate is not None:
            prev_value_cell.value = prev_rate
            prev_value_cell.number_format = "0.000000"
        else:
            prev_value_cell.value = "—"

        # Zenith
        zenith_cell = ws.cell(row=row, column=4, value=1.0 / cur_rate if cur_rate else 0)
        zenith_cell.font = BODY_FONT
        zenith_cell.alignment = RIGHT
        zenith_cell.border = THIN_BORDER
        zenith_cell.number_format = "0.000000"

        row += 1

    # Column widths — Currency | Current | Previous | Zenith
    widths = {"A": 14, "B": 26, "C": 22, "D": 16}
    for col, w in widths.items():
        ws.column_dimensions[col].width = w


def _write_usd_current_cell(cell, rate: float, tracker: UsdTracker, run_date: date) -> None:
    """Render USD current-day value with `(DD-MMM-YY)` suffix.

    Uses rich-text (mixed colors) when openpyxl's lxml writer is available, so the
    rate stays black/bold and only the date bracket is red. Falls back to a plain
    string with the whole cell red when lxml is missing — openpyxl's pure-python
    CellRichText writer has a known bug that corrupts the xlsx on save.
    """
    date_str = tracker.last_changed_date.strftime("%d-%b-%y").upper()
    rate_str = _format_rate(rate)

    if _has_lxml_rich_text():
        try:
            from openpyxl.cell.rich_text import CellRichText, TextBlock
            from openpyxl.cell.text import InlineFont

            cell.value = CellRichText(
                TextBlock(InlineFont(rFont="Calibri", sz=11, b=True), f"{rate_str}  "),
                TextBlock(
                    InlineFont(rFont="Calibri", sz=11, b=True, color=USD_DATE_FONT_COLOR),
                    f"({date_str})",
                ),
            )
            return
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("  Rich-text USD cell failed (%s); using plain fallback.", exc)

    cell.value = f"{rate_str}  ({date_str})"
    cell.font = Font(name="Calibri", size=11, bold=True, color=USD_DATE_FONT_COLOR)


def _has_lxml_rich_text() -> bool:
    """True when lxml is importable — required for openpyxl rich-text writes."""
    try:
        import lxml  # noqa: F401
    except ImportError:
        return False
    return True


def _format_rate(rate: float) -> str:
    # Trim trailing zeros but keep at least 2 decimals, match image style.
    formatted = f"{rate:.6f}".rstrip("0").rstrip(".")
    if "." not in formatted:
        formatted += ".00"
    elif len(formatted.split(".")[1]) < 2:
        formatted = f"{rate:.2f}"
    return formatted


def _rates_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol
