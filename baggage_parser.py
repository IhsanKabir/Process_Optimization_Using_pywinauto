"""
baggage_parser.py — Parse FQC baggage allowance from Smartpoint terminal output.

Handles: FQCBS/ET output containing BAGGAGE ALLOWANCE and CARRY ON ALLOWANCE blocks.
"""
from __future__ import annotations

import re


def parse_baggage_allowance(text: str) -> dict:
    """
    Extract checked and carry-on baggage allowance from FQCXX/ET response text.

    Example input section:
        BAGGAGE ALLOWANCE
        ADT
         BS DACDXB  30K
           BAG 1 -  CHGS MAY APPLY ...
        CARRY ON ALLOWANCE
         BS DACDXB  07K

    Returns:
        {"checked": "30K", "carry_on": "07K", "route": "DACDXB"}
        or {} if no baggage data found.
    """
    checked = ""
    carry_on = ""
    route = ""

    in_checked = False
    in_carry_on = False

    for line in text.splitlines():
        upper = line.upper().strip()

        if "BAGGAGE ALLOWANCE" in upper and "CARRY" not in upper:
            in_checked = True
            in_carry_on = False
            continue

        if "CARRY ON ALLOWANCE" in upper or "CARRY-ON ALLOWANCE" in upper:
            in_carry_on = True
            in_checked = False
            continue

        if not (in_checked or in_carry_on):
            continue

        # Skip passenger type lines (ADT, CHD, INF, etc.) and note lines
        stripped = line.strip()
        if re.match(r"^(?:ADT|CHD|INF|CNN)$", stripped, re.IGNORECASE):
            continue
        if stripped.startswith("BAG ") or stripped.startswith("VIEW"):
            continue

        # Match: "  BS DACDXB  30K"  or "  BS DACDXB  1PC"
        m = re.match(
            r"^\s{1,6}[A-Z0-9]{2}\s+([A-Z]{3,8})\s+(\d+(?:PC|K|P))\b",
            line,
            re.IGNORECASE,
        )
        if m:
            if in_checked and not checked:
                route = m.group(1).upper()
                checked = m.group(2).upper()
                in_checked = False
            elif in_carry_on and not carry_on:
                carry_on = m.group(2).upper()
                in_carry_on = False

    if checked or carry_on:
        return {"checked": checked, "carry_on": carry_on, "route": route}
    return {}


def is_no_bf_error(text: str) -> bool:
    """Return True when the terminal says no booking file exists."""
    return "NO B.F. TO DISPLAY" in text.upper()
