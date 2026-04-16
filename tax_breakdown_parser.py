import re

# Pre-compiled regex patterns for tax breakdown parsing
_RE_BASE_FARE = re.compile(r"FARE\s+([A-Z]{3})\s*(\d+\.?\d*)")
_RE_EQU_FARE = re.compile(r"EQU\s+([A-Z]{3})\s*(\d+\.?\d*)")
_RE_YQ_CHARGE = re.compile(r"\bYQ\s*(\d+\.?\d*)\b")
_RE_YR_CHARGE = re.compile(r"\bYR\s*(\d+\.?\d*)\b")
_RE_Q_CHARGE = re.compile(r"\bQ\s*(\d+\.?\d*)\b")
_RE_TAXES = re.compile(r"TAXES\s+([A-Z]{3})?\s*(\d+\.?\d*)")
_RE_TOTAL = re.compile(r"TOT\s+([A-Z]{3})?\s*(\d+\.?\d*)")
_RE_TAX_CODES = re.compile(r"\b([A-Z][A-Z0-9]?)(\d+\.?\d*)\b")

FS_DETAIL_MARKERS = [
    "TOTAL JOURNEY TIME",
    "FS-1 ADT",
    "REFUNDABLE:",
    "LAST DATE TO PURCHASE TICKET",
    "PLATING CARRIER:",
    "ADDITIONAL TAXES, SURCHARGES, OR FEES MAY APPLY",
]


def parse_fs_tax_breakdown(text: str) -> dict:
    """
    Parses the expanded tax breakdown from an FS command and returns a dictionary
    containing Base Fare, Equivalent Fare, YQ/YR/Q charges, and Total Taxes.

    Example text:
    DAC BS MLE 177.00OBDMVO NUC177.00END ROE1.0
    FARE USD177.00 EQU BDT21720 BD500 OW1000 P7614 P8737 UT2000 E5278
    YQ246 TAXES BDT5375 TOT BDT27095
    """
    result = {
        "base_currency": None,
        "base_fare": 0.0,
        "equ_currency": None,
        "equ_fare": 0.0,
        "yq_charge": 0.0,
        "yr_charge": 0.0,
        "q_charge": 0.0,
        "total_taxes": 0.0,
        "total_amount": 0.0,
        "exchange_rate": 0.0,
        "tax_breakdown": {},
    }

    # 1. Base Fare
    base_match = _RE_BASE_FARE.search(text)
    if base_match:
        result["base_currency"] = base_match.group(1)
        result["base_fare"] = float(base_match.group(2))

    # 2. Equivalent Fare
    equ_match = _RE_EQU_FARE.search(text)
    if equ_match:
        result["equ_currency"] = equ_match.group(1)
        result["equ_fare"] = float(equ_match.group(2))

    # 3. YQ, YR, Q Charges
    yq_match = _RE_YQ_CHARGE.search(text)
    if yq_match:
        result["yq_charge"] = float(yq_match.group(1))

    yr_match = _RE_YR_CHARGE.search(text)
    if yr_match:
        result["yr_charge"] = float(yr_match.group(1))

    q_match = _RE_Q_CHARGE.search(text)
    if q_match:
        result["q_charge"] = float(q_match.group(1))

    # 4. Total Taxes & Total Amount
    tax_match = _RE_TAXES.search(text)
    if tax_match:
        result["total_taxes"] = float(tax_match.group(2))

    tot_match = _RE_TOTAL.search(text)
    if tot_match:
        result["total_amount"] = float(tot_match.group(2))

    # 5. Extract specific tax breakdown array
    # Look for 1 or 2 character IATA tax codes (Letter + Letter/Digit) followed immediately by numbers (e.g. BD500, P7614)
    # Only search from the "FARE" keyword onwards to avoid false positives from
    # flight segment lines (e.g. aircraft type "DH8" parsed as tax code "DH").
    exclude_codes = {"YQ", "YR", "TOT", "EQU", "NUC", "ROE", "USD", "BDT", "EUR", "GBP"}
    fare_pos = text.find("FARE")
    tax_search_text = text[fare_pos:] if fare_pos >= 0 else text
    tax_codes = _RE_TAX_CODES.findall(tax_search_text)

    # Process multiple of the same code by adding them, but keep different codes separate
    for code, amt in tax_codes:
        if code not in exclude_codes:
            val = float(amt)
            if code in result["tax_breakdown"]:
                result["tax_breakdown"][code] += val
            else:
                result["tax_breakdown"][code] = val

    # Calculate exchange rate dynamically after all fields are parsed.
    if result["base_fare"] > 0 and result["equ_fare"] > 0:
        result["exchange_rate"] = round(result["equ_fare"] / result["base_fare"], 4)
    elif result["base_fare"] > 0 or result["equ_fare"] > 0:
        # If only one fare side is present, keep the available currency data usable.
        result["exchange_rate"] = 1.0
    elif (
        result["total_taxes"] > 0
        or result["total_amount"] > 0
        or result["yq_charge"] > 0
        or result["yr_charge"] > 0
        or result["q_charge"] > 0
        or result["tax_breakdown"]
    ):
        # Some airlines render tax details without both fare lines.
        result["exchange_rate"] = 1.0

    return result


def looks_like_fs_tax_breakdown(text: str) -> bool:
    """Return True when the captured FS text looks like a valid detail expansion."""
    if not text or not text.strip():
        return False

    upper = text.upper()
    if any(marker in upper for marker in FS_DETAIL_MARKERS):
        return True

    parsed = parse_fs_tax_breakdown(text)
    numeric_keys = (
        "base_fare",
        "equ_fare",
        "yq_charge",
        "yr_charge",
        "q_charge",
        "total_taxes",
        "total_amount",
    )
    return any(parsed.get(key, 0) > 0 for key in numeric_keys) or bool(
        parsed.get("tax_breakdown")
    )
