"""
parser.py - GDS Fare Display Output Parser

Parses raw text output from Travelport Smartpoint fare display commands
into structured data for report generation.

Command format: FD{ORIGIN}{DEST}-{OW|RT}/{AIRLINE}
Example: FDDACMLE-OW/BG -> One-way fares from DAC to MLE on BG
"""

import re
import logging
from typing import Optional

logger = logging.getLogger("travelport.parser")


def parse_command(command: str) -> Optional[dict]:
    """
    Parse a fare display mother command string into its components.

    Example: FDDACMLE/BG
    Returns: {origin: DAC, dest: MLE, airline: BG, route: DAC-MLE}
    """
    pattern = r"^FD([A-Z]{3})([A-Z]{3})/([A-Z0-9]{2})$"
    match = re.match(pattern, command.strip(), re.IGNORECASE)

    if not match:
        return None

    origin = match.group(1).upper()
    dest = match.group(2).upper()
    airline = match.group(3).upper()

    return {
        "origin": origin,
        "destination": dest,
        "airline": airline,
        "route": f"{origin}-{dest}",
        "command": command.strip().upper(),
    }


def load_commands_from_text(text: str) -> list[dict]:
    """Parse commands from a raw string block."""
    commands = []
    lines = text.strip().split("\n")
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        parsed = parse_command(line)
        if parsed:
            commands.append(parsed)
        else:
            logger.warning("Could not parse command: %s", line)
    return commands


def load_commands(commands_file: str) -> list[dict]:
    """
    Load and parse commands from the commands.txt file.
    Skips comment lines (starting with #) and empty lines.

    Returns list of parsed command dicts.
    """
    try:
        with open(commands_file, "r", encoding="utf-8") as f:
            content = f.read()
        return load_commands_from_text(content)
    except Exception as e:
        logger.error("Failed to load commands file: %s", e)
        return []


def _extract_currency(raw_text: str):
    """
    Extract the currency code from the fare display header.

    Looks for patterns like:
        '         USD    BASIS       MAX'
        '         CNY    BASIS       MAX'
        '         OMR    BASIS       MAX'
    """
    lines = raw_text.strip().split("\n")
    for line in lines:
        # Match the column header line that shows the currency code
        # e.g. "         USD    BASIS       MAX" or "    CNY    BASIS"
        match = re.search(r"\b([A-Z]{3})\s+BASIS\b", line.upper())
        if match:
            return match.group(1)
    return None


def parse_fare_display(raw_text: str) -> dict:
    """
    Parse raw GDS fare display output into structured fare records.

    Extracts currency from the fare display header automatically.
    Handles both sellable and unsaleable fares (O-prefixed line numbers).

    Returns:
        Dict with keys:
            'fares': List of fare dicts
            'currency': Extracted currency code (e.g., 'USD', 'CNY', 'OMR')
    """
    if not raw_text or not raw_text.strip():
        return {"fares": [], "currency": None}

    # Extract currency from the header
    # Patterns found in Smartpoint output:
    #   "BDT CURRENCY FARES EXIST"  (alternative currency notice)
    #   "    FARE"  line followed by "    USD    BASIS" or "    CNY    BASIS"
    #   Column header line like: "         USD    BASIS       MAX"
    currency = _extract_currency(raw_text)

    fares = []
    lines = raw_text.strip().split("\n")

    # Pattern to match fare lines
    # Groups: (line_num) (airline) (fare)(R?) (fare_basis) (rbd) ... rest
    # Line numbers can be normal digits OR O-prefixed (O30, O31) for unsellable fares
    fare_pattern = re.compile(
        r"^\s*O?(\d+)\s+"  # Line number (optionally O-prefixed for unsellable)
        r"-?([A-Z0-9]{2})\s+"  # Optional minus sign, then Airline code (2 chars)
        r"(\d+\.?\d*)(R?)\s+"  # Fare amount + optional R (round-trip marker)
        r"(\S+)\s+"  # Fare basis code
        r"([A-Z])(?:\s+(.*))?$",  # RBD followed by optional trailing columns
        re.IGNORECASE,
    )

    # Pre-compiled: avoids re-compiling on every iteration
    line_num_pattern = re.compile(r"^\s*O?\d+\s+")

    is_unsellable_section = False

    for line in lines:
        stripped = line.strip()
        upper_stripped = stripped.upper()
        if not stripped:
            continue

        # Detect strict unsaleable section break injected by automation
        if "--- UNSALEABLE FARES BREAK ---" in upper_stripped:
            is_unsellable_section = True
            continue

        # Skip non-fare lines
        if upper_stripped in ("END", "MD"):
            continue
        # Match lines starting with a digit (and properly handle leading zeroes like '030')
        if not line_num_pattern.match(line):
            continue

        match = fare_pattern.match(line)
        if match:
            line_num = int(match.group(1))
            airline = match.group(2).upper()
            fare_amount = float(match.group(3))
            fare_basis = match.group(5).upper()
            rbd = match.group(6).upper()
            line_token_match = re.match(r"^\s*(O?\d+)", line, re.IGNORECASE)
            line_token = (
                line_token_match.group(1).upper() if line_token_match else str(line_num)
            )

            # Check if this line was O-prefixed (unsellable indicator)
            is_o_prefixed = bool(re.match(r"^\s*O\d+", line))

            fares.append(
                {
                    "line": line_num,
                    "line_token": line_token,
                    "airline": airline,
                    "fare": fare_amount,
                    "is_rt": bool(match.group(4)),  # Group 4 is (R?)
                    "fare_basis": fare_basis,
                    "rbd": rbd,
                    "is_unsaleable": is_unsellable_section or is_o_prefixed,
                    "raw_line": stripped,
                }
            )

    return {"fares": fares, "currency": currency}


def group_fares_by_rbd(fares: list[dict], rbd_sort_order: list[str] = None) -> dict:
    """
    Group parsed fares by RBD, extracting both OW and RT fares for each RBD,
    and capturing the lowest fare amount for each type.

    IMPORTANT: Unsaleable fares are kept separate from saleable fares even if
    they have the same RBD. This is done by creating separate dictionary keys
    with " (Unsaleable)" suffix.

    Returns:
        Dict keyed by RBD -> {
            'rbd': str,
            'ow_fare': float/None,
            'rt_fare': float/None,
            'ow_fare_basis': str/None,
            'rt_fare_basis': str/None
        }
    """
    rbd_data = {}

    for fare in fares:
        rbd = fare["rbd"]

        # Create separate keys for unsaleable fares to preserve both
        # saleable and unsaleable fares even when RBDs duplicate
        if fare.get("is_unsaleable"):
            key = f"{rbd} (Unsaleable)"
        else:
            key = rbd

        if key not in rbd_data:
            rbd_data[key] = {
                "rbd": key,
                "ow_fare": None,
                "rt_fare": None,
                "ow_fare_basis": None,
                "rt_fare_basis": None,
            }

        fare_basis = fare["fare_basis"]
        if fare.get("is_unsaleable") and "(Unsaleable)" not in fare_basis:
            fare_basis = f"{fare_basis} (Unsaleable)"

        if fare["is_rt"]:
            if (
                rbd_data[key]["rt_fare"] is None
                or fare["fare"] < rbd_data[key]["rt_fare"]
            ):
                rbd_data[key]["rt_fare"] = fare["fare"]
                rbd_data[key]["rt_fare_basis"] = fare_basis
        else:  # is OW
            if (
                rbd_data[key]["ow_fare"] is None
                or fare["fare"] < rbd_data[key]["ow_fare"]
            ):
                rbd_data[key]["ow_fare"] = fare["fare"]
                rbd_data[key]["ow_fare_basis"] = fare_basis

    # Sort by RBD order
    if rbd_sort_order:

        def sort_key(item):
            try:
                return rbd_sort_order.index(item[0])
            except ValueError:
                return len(rbd_sort_order)

        rbd_data = dict(sorted(rbd_data.items(), key=sort_key))
    else:
        rbd_data = dict(sorted(rbd_data.items()))

    return rbd_data


def select_report_fare_targets(
    fares: list[dict], rbd_sort_order: list[str] = None
) -> list[dict]:
    """
    Return only the unique lowest fare lines that would appear in the report.

    This is used by the penalty workflow so we only click the fare basis rows
    that survive the report grouping logic, instead of every visible fare line.
    """
    grouped_fares = group_fares_by_rbd(fares, rbd_sort_order)
    selected_fares = []
    seen_keys = set()

    for grouped_rbd, grouped_data in grouped_fares.items():
        is_unsaleable_group = "(Unsaleable)" in grouped_rbd
        target_specs = []

        if (
            grouped_data.get("ow_fare_basis") is not None
            and grouped_data.get("ow_fare") is not None
        ):
            target_specs.append(
                (
                    False,
                    grouped_data["ow_fare_basis"],
                    grouped_data["ow_fare"],
                    is_unsaleable_group,
                )
            )

        if (
            grouped_data.get("rt_fare_basis") is not None
            and grouped_data.get("rt_fare") is not None
        ):
            target_specs.append(
                (
                    True,
                    grouped_data["rt_fare_basis"],
                    grouped_data["rt_fare"],
                    is_unsaleable_group,
                )
            )

        for is_rt, fare_basis, fare_amount, is_unsaleable in target_specs:
            normalized_basis = fare_basis.replace(" (Unsaleable)", "")
            matching_fares = [
                fare
                for fare in fares
                if fare.get("is_rt") == is_rt
                and fare.get("fare_basis") == normalized_basis
                and fare.get("fare") == fare_amount
                and bool(fare.get("is_unsaleable")) == is_unsaleable
            ]

            if not matching_fares:
                continue

            target_fare = min(matching_fares, key=lambda item: item["line"])
            target_key = (
                grouped_rbd,
                fare_basis,
                fare_amount,
                is_rt,
            )

            if target_key in seen_keys:
                continue

            seen_keys.add(target_key)
            selected_fares.append(target_fare)

    return sorted(selected_fares, key=lambda item: item["line"])


def generate_file_key(command_info: dict) -> str:
    """
    Generate a consistent file key for a command.
    Used for naming raw data text files.

    Example: FDDACMLE/BG -> BG_DAC-MLE
    """
    return f"{command_info['airline']}_{command_info['route']}"


if __name__ == "__main__":
    # Quick test with sample data
    print("=== Command parsing ===")
    test_cmds = ["FDDACMLE/BG", "FDMLEDAC/BG"]
    for c in test_cmds:
        parsed = parse_command(c)
        print(f"  {c} -> {parsed}")

    print("\n=== Fare display parsing ===")
    sample = """FARES LAST UPDATED 14MAR 17:04 P
BG        DAC CGP DEPART 14MAR
**ADDITIONAL TAXES/FEES MAY APPLY**
PUBLIC FARES
BDT CURRENCY FARES EXIST
    CX   FARE   FARE   C AP MIN/    SEASONS...... MR GI DT
         USD    BASIS       MAX
DACCGP
  1 -BG  100.00   YOW      Y                            R  EH
  2  BG  200.00R  JRT      J                            R  EH
  3 -BG  150.00   COW      C                            R  EH
  4  BG  80.00    NOW      N                            R  EH
END"""

    result = parse_fare_display(sample)
    fares = result["fares"]
    print(f"  Currency: {result['currency']}")
    for f in fares:
        rt_marker = "RT" if f["is_rt"] else "OW"
        print(
            f"  Line {f['line']}: {f['airline']} {f['rbd']} ${f['fare']:.2f} {rt_marker} ({f['fare_basis']})"
        )

    print("\n=== Group by RBD ===")
    grouped = group_fares_by_rbd(fares)
    for rbd, data in grouped.items():
        print(f"  {rbd}: OW ${data['ow_fare']} RT ${data['rt_fare']}")
