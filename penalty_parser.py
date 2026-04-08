"""
penalty_parser.py - Parse Travelport Rule 16 penalty text.

Extracts the Rule 16 penalty section from Smartpoint popup captures and turns it
into structured penalty rules keyed to a specific fare basis.
"""

from __future__ import annotations

import re
from typing import Optional

FARE_LINE_PATTERN = re.compile(
    r"^\s*O?(\d+)\s+-?([A-Z0-9]{2})\s+(\d+\.?\d*)(R?)\s+(\S+)\s+([A-Z])(?:\s+.*)?$",
    re.IGNORECASE,
)

CHARGE_PATTERN = re.compile(
    r"^CHARGE\s+([A-Z]{3})\s*([0-9]+(?:\.[0-9]+)?)\s+FOR\s+(.+?)(?:\.)?$",
    re.IGNORECASE,
)

CATEGORY_HEADINGS = {"CHANGES", "CANCELLATIONS"}
CONDITION_PREFIXES = (
    "ANY TIME",
    "BEFORE ",
    "AFTER ",
    "FOR ",
    "IF ",
    "WHEN ",
    "UNLESS ",
    "UP TO ",
    "UPTO ",
    "MORE THAN ",
    "LESS THAN ",
    "NO SHOW",
    "ON/AFTER ",
    "ON/BEFORE ",
    "PRIOR TO ",
)


def extract_penalty_section(raw_text: str) -> str:
    """Return only the Rule 16 penalty block from a mixed Smartpoint capture."""
    if not raw_text:
        return ""

    lines = raw_text.splitlines()
    start_index = None
    for index, line in enumerate(lines):
        if "16. PENALTIES" in line.upper():
            start_index = index
            break

    if start_index is None:
        return ""

    collected = []
    started = False
    for line in lines[start_index:]:
        stripped = line.strip()
        if not started and not stripped:
            continue

        started = True
        if collected and (FARE_LINE_PATTERN.match(line) or stripped == "END"):
            break

        collected.append(line.rstrip())

    return "\n".join(collected).strip()


def _is_condition_line(text: str) -> bool:
    upper_text = text.upper()
    if not upper_text:
        return False
    if upper_text.startswith("UNLESS OTHERWISE SPECIFIED"):
        return False
    if upper_text in CATEGORY_HEADINGS:
        return False
    if upper_text.startswith("CHARGE "):
        return False
    if upper_text.startswith("NOTE -"):
        return False
    if " PERMITTED." in upper_text or "NOT PERMITTED" in upper_text:
        return False
    if "NON-REFUNDABLE" in upper_text or upper_text.startswith("NO REFUND"):
        return False
    if upper_text == "ALSO APPLIES":
        return False

    return upper_text.startswith(CONDITION_PREFIXES)


def _is_rule_line(text: str) -> bool:
    upper_text = text.upper()
    return bool(
        CHARGE_PATTERN.match(text)
        or " PERMITTED." in upper_text
        or "NOT PERMITTED" in upper_text
        or "NON-REFUNDABLE" in upper_text
        or upper_text.startswith("NO REFUND")
    )


def _infer_rule_subtype(category: str, description: str) -> str:
    upper_description = description.upper()

    if "NO-SHOW" in upper_description or "NO SHOW" in upper_description:
        return "no_show"

    if category == "CHANGES":
        return "change"

    if category == "CANCELLATIONS":
        return "refund"

    return "other"


def _parse_rule_line(category: str, line_text: str) -> dict:
    line_text = line_text.strip()
    charge_match = CHARGE_PATTERN.match(line_text)
    if charge_match:
        currency = charge_match.group(1).upper()
        amount = float(charge_match.group(2))
        description = charge_match.group(3).strip()
        return {
            "category": category,
            "subtype": _infer_rule_subtype(category, description),
            "amount": amount,
            "currency": currency,
            "description": description,
            "status": "charged",
        }

    upper_text = line_text.upper()
    status = "informational"
    if (
        "NOT PERMITTED" in upper_text
        or "NON-REFUNDABLE" in upper_text
        or upper_text.startswith("NO REFUND")
    ):
        status = "not_permitted"
    elif " PERMITTED." in upper_text:
        status = "permitted"

    return {
        "category": category,
        "subtype": _infer_rule_subtype(category, line_text),
        "amount": None,
        "currency": None,
        "description": line_text.rstrip("."),
        "status": status,
    }


def parse_penalty_text(
    raw_text: str,
    *,
    airline: Optional[str] = None,
    route: Optional[str] = None,
    fare_basis: Optional[str] = None,
    rbd: Optional[str] = None,
    fare_amount: Optional[float] = None,
    journey_type: Optional[str] = None,
) -> dict:
    """
    Parse a Smartpoint penalty popup capture for one fare basis.

    Returns a dictionary with metadata plus a list of structured rules.
    """
    penalty_text = extract_penalty_section(raw_text)
    if not penalty_text:
        return {
            "airline": airline,
            "route": route,
            "fare_basis": fare_basis,
            "rbd": rbd,
            "fare_amount": fare_amount,
            "journey_type": journey_type,
            "raw_penalty_text": "",
            "rules": [],
        }

    rules = []
    category = None
    context_stack = []
    lines = penalty_text.splitlines()
    index = 0

    while index < len(lines):
        raw_line = lines[index].rstrip()
        stripped = raw_line.strip()
        upper_text = stripped.upper()

        if not stripped or upper_text == "16. PENALTIES":
            index += 1
            continue

        indent = len(raw_line) - len(raw_line.lstrip(" "))

        if upper_text in CATEGORY_HEADINGS:
            category = upper_text
            index += 1
            continue

        if _is_condition_line(stripped):
            while context_stack and context_stack[-1][0] >= indent:
                context_stack.pop()
            context_stack.append((indent, stripped))
            index += 1
            continue

        if not category or not _is_rule_line(stripped):
            index += 1
            continue

        rule = _parse_rule_line(category, stripped)
        rule["criteria_text"] = " | ".join(item[1] for item in context_stack)
        rule["raw_line"] = stripped

        note_lines = []
        look_ahead = index + 1
        while look_ahead < len(lines):
            next_raw_line = lines[look_ahead].rstrip()
            next_stripped = next_raw_line.strip()
            next_upper = next_stripped.upper()
            next_indent = len(next_raw_line) - len(next_raw_line.lstrip(" "))

            if not next_stripped:
                look_ahead += 1
                continue

            if next_upper == "NOTE -":
                look_ahead += 1
                while look_ahead < len(lines):
                    note_raw_line = lines[look_ahead].rstrip()
                    note_stripped = note_raw_line.strip()
                    note_upper = note_stripped.upper()
                    note_indent = len(note_raw_line) - len(note_raw_line.lstrip(" "))

                    if not note_stripped:
                        look_ahead += 1
                        continue

                    if note_stripped and set(note_stripped) == {"-"}:
                        look_ahead += 1
                        continue

                    if note_indent <= next_indent and (
                        note_upper in CATEGORY_HEADINGS
                        or _is_condition_line(note_stripped)
                        or _is_rule_line(note_stripped)
                    ):
                        break

                    note_lines.append(note_stripped)
                    look_ahead += 1
                break

            if (
                next_upper in CATEGORY_HEADINGS
                or _is_condition_line(next_stripped)
                or _is_rule_line(next_stripped)
            ):
                break

            if next_indent > indent:
                note_lines.append(next_stripped)
                look_ahead += 1
                continue

            break

        rule["note_text"] = "\n".join(note_lines).strip()
        rules.append(rule)
        index = look_ahead

    return {
        "airline": airline,
        "route": route,
        "fare_basis": fare_basis,
        "rbd": rbd,
        "fare_amount": fare_amount,
        "journey_type": journey_type,
        "raw_penalty_text": penalty_text,
        "rules": rules,
    }
