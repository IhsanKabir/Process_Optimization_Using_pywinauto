"""report_run_info.py - What a fare report was built from, stored in the report.

Re-run missing rewrites the original report instead of making a new one. To
do that it needs the report's route list and the change markers the original
run showed, so every fare report keeps them as JSON in a hidden sheet.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime

logger = logging.getLogger(__name__)

RUN_INFO_SHEET = "_run_info"
RUN_INFO_VERSION = 1
# Excel cells hold at most 32,767 characters; the JSON is split across rows.
_CHUNK = 30000


def write_run_info(wb, routes, changes: dict | None, no_fare_routes=()) -> None:
    """Add the hidden run-info sheet to an openpyxl workbook.

    ``no_fare_routes`` are routes Smartpoint showed no fares for; they are
    not listed for re-run again when the report is rewritten.
    """
    payload = json.dumps(
        {
            "version": RUN_INFO_VERSION,
            "routes": sorted(routes),
            "changes": changes or {},
            "no_fares": sorted(no_fare_routes),
        },
        default=str,
    )
    ws = wb.create_sheet(RUN_INFO_SHEET)
    for i in range(0, len(payload), _CHUNK):
        ws.cell(row=i // _CHUNK + 1, column=1, value=payload[i : i + _CHUNK])
    ws.sheet_state = "veryHidden"


def read_run_info(path: str) -> dict | None:
    """The run info saved in a report, or None (older report, unreadable)."""
    from openpyxl import load_workbook

    try:
        wb = load_workbook(path, read_only=True)
    except Exception as exc:
        logger.warning("  Could not open report %s: %s", path, exc)
        return None
    try:
        if RUN_INFO_SHEET not in wb.sheetnames:
            return None
        text = "".join(
            str(row[0] or "")
            for row in wb[RUN_INFO_SHEET].iter_rows(max_col=1, values_only=True)
        )
    finally:
        wb.close()
    try:
        info = json.loads(text)
    except ValueError:
        return None
    if not isinstance(info, dict) or not isinstance(info.get("routes"), list):
        return None
    if not isinstance(info.get("changes"), dict):
        info["changes"] = {}
    if not isinstance(info.get("no_fares"), list):
        info["no_fares"] = []
    return info


def merge_rerun_changes(original: dict, detected: dict | None, rerun_keys) -> dict:
    """Change markers for a report rewritten by Re-run missing.

    Routes that were not re-run keep the markers the original report showed.
    A re-run route keeps them too, unless its fares changed since the original
    run (``detected`` compares against that run), in which case the new
    changes are shown.
    """
    merged = {k: v for k, v in (original or {}).items() if v}
    for key in rerun_keys:
        if detected and detected.get(key):
            merged[key] = detected[key]
    return merged


def backup_report(path: str) -> str:
    """Copy a report into a backup folder beside it before it is rewritten."""
    folder = os.path.join(os.path.dirname(path) or ".", "backup")
    os.makedirs(folder, exist_ok=True)
    stem, ext = os.path.splitext(os.path.basename(path))
    dest = os.path.join(folder, f"{stem}_before_rerun_{datetime.now():%H%M%S}{ext}")
    shutil.copy2(path, dest)
    return dest
