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

WORD_NUMBERS = {
    "ONE": 1,
    "TWO": 2,
    "THREE": 3,
    "FOUR": 4,
    "FIVE": 5,
    "SIX": 6,
    "SEVEN": 7,
    "EIGHT": 8,
    "NINE": 9,
    "TEN": 10,
    "ELEVEN": 11,
    "TWELVE": 12,
    "TWENTY FOUR": 24,
}

TIMING_PATTERN = re.compile(
    r"(?:(AT LEAST|UP TO|UPTO|MORE THAN|LESS THAN|WITHIN)\s+)?"
    r"(\d+|ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE|TEN|ELEVEN|TWELVE|TWENTY(?:[- ]FOUR)?)\s+"
    r"(MINUTE|MINUTES|HOUR|HOURS|DAY|DAYS|MONTH|MONTHS)\s+"
    r"(BEFORE|AFTER)\s+"
    r"(?:THE\s+)?"
    r"(FLIGHT\s+DEPARTURE|DEPARTURE\s+OF\s+THE\s+FLIGHT|DEPARTURE|SCHEDULED\s+DEPARTURE)",
    re.IGNORECASE,
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


def _parse_number_token(token: str) -> Optional[int]:
    normalized = re.sub(r"[-\s]+", " ", (token or "").upper()).strip()
    if not normalized:
        return None
    if normalized.isdigit():
        return int(normalized)
    return WORD_NUMBERS.get(normalized)


def _extract_timing_details(*texts: str) -> dict:
    combined_text = " ".join(text for text in texts if text)
    combined_text = re.sub(r"\s+", " ", combined_text).strip()
    if not combined_text:
        return {
            "timing_text": "",
            "timing_qualifier": None,
            "timing_value": None,
            "timing_unit": None,
            "timing_direction": None,
            "timing_reference": None,
        }

    match = TIMING_PATTERN.search(combined_text)
    if not match:
        return {
            "timing_text": "",
            "timing_qualifier": None,
            "timing_value": None,
            "timing_unit": None,
            "timing_direction": None,
            "timing_reference": None,
        }

    qualifier = match.group(1)
    unit = match.group(3).lower()
    if unit.endswith("s"):
        unit = unit[:-1]

    return {
        "timing_text": match.group(0),
        "timing_qualifier": qualifier.lower().replace(" ", "_") if qualifier else None,
        "timing_value": _parse_number_token(match.group(2)),
        "timing_unit": unit,
        "timing_direction": match.group(4).lower(),
        "timing_reference": "departure",
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
        rule.update(
            _extract_timing_details(
                rule.get("criteria_text", ""),
                rule.get("description", ""),
                rule.get("note_text", ""),
            )
        )
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
