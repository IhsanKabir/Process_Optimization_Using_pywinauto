"""
tax_parser.py - FTAX Tax Display Output Parser

Parses raw text output from Travelport Smartpoint FTAX commands
into structured data for tax report generation.

Command flow:
  FTAX-SG          → list of tax types for Singapore
  FTAX-SG/L7       → detail for tax type L7
  MD               → paginate through details
"""

import re
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger("travelport.tax_parser")

# Pre-compiled regex patterns
_RE_FTAX_LIST = re.compile(r"(.+?)>FTAX-[A-Z]{2}/([A-Z0-9]{2,3})")
_RE_AMOUNT_CHECK = re.compile(r"(?:\s|^)[A-Z]{3}\s+\d+\.?\d*\s*$")
_RE_AMOUNT = re.compile(r"(?:\s|^)([A-Z]{3})\s*(\d+(?:\.\d+)?)\s*$")
_RE_LEADING_DASH = re.compile(r"^[-–]\s*")
_RE_AIRPORT_CODE = re.compile(r"^[A-Z]{3}\s*[-–]\s+[A-Z]")
_RE_HAS_AMOUNT = re.compile(r"(?:\s|^)[A-Z]{3}\s*\d+\.\d+\s*$")
_RE_DATE = re.compile(r"(\d{2})([A-Z]{3})(\d{2,4})")
# Percent-based rates: "15 PERCENT ON EMBARKATION FEE - BD" or
#                      "15 PERCENT OF APPLICABLE EMBARKATION -BD- FEE."
_RE_PERCENT = re.compile(
    r"^(\d+(?:\.\d+)?)\s+PERCENT\s+(?:ON|OF)\s+(.+?)\s*\.?\s*$",
    re.IGNORECASE,
)
_RE_BASIS_CODE_TRAILING = re.compile(r"\s+-+\s*([A-Z][A-Z0-9]?)\s*$")
_RE_BASIS_CODE_EMBEDDED = re.compile(r"-([A-Z][A-Z0-9]?)-")
# Standalone condition line that precedes percent rates (no currency+amount on same line)
_RE_DATE_COND = re.compile(
    r"\b(?:TKT(?:/TVL)?|TVL)\b.+\b(?:ON/BEFORE|ON/AFTER)\b",
    re.IGNORECASE,
)


def parse_ftax_list(raw_text: str) -> list[dict]:
    """
    Parse the output of FTAX-{CC} to extract available tax type codes.

    Example lines:
        L7 - AIRPORT DEVELOPMENT LEVY        SIN
        OP - PASSENGER SERVICE CHARGE         SIN
        C8 - AVIATION LEVY                    SIN

    Returns list of: {'code': 'L7', 'name': 'AIRPORT DEVELOPMENT LEVY', 'airports': 'SIN'}
    """
    tax_types = []
    lines = raw_text.strip().split("\n")

    # Pattern expects format like:
    # AIRPORT DEVELOPMENT LEVY              >FTAX-SG/L7·
    # Name...                              >FTAX-{CC}/{CODE}[junk]
    for line in lines:
        match = _RE_FTAX_LIST.search(line.strip())
        if match:
            name = match.group(1).strip()
            code = match.group(2).strip()

            tax_types.append(
                {
                    "code": code,
                    "name": name,
                    "airports": "",  # Airport info isn't in this format
                }
            )

    return tax_types


def parse_ftax_detail(raw_text: str, tax_code: str = "", tax_name: str = "") -> dict:
    """
    Parse the output of FTAX-{CC}/{TYPE} (after MD pagination)
    into structured tax rate data.

    The input may contain multiple pages joined by '--- PAGE BREAK ---'.
    Each page is a Ctrl+A/Ctrl+C capture, so pages may have overlapping content.

    The FTAX detail output has this structure:
        TAX RATE section header
        Departure category headers (e.g., "DEPARTURES FROM CHANGI SIN")
        Terminal groupings (e.g., "INTERNATIONAL DEPARTURES FROM TERMINAL 1 2 3")
        Condition lines with amounts (e.g., "-TKT ON/BEFORE 31MAR25    SGD 46.40")

    Returns:
        {
            'code': 'L7',
            'name': 'AIRPORT DEVELOPMENT LEVY',
            'sections': [
                {
                    'category': 'DEPARTURES FROM CHANGI SIN',
                    'subcategory': 'INTERNATIONAL DEPARTURES FROM TERMINAL 1 2 3',
                    'rates': [
                        {
                            'condition': 'TKT ON/BEFORE 31MAR25',
                            'currency': 'SGD',
                            'amount': 46.40,
                            'status': 'expired' | 'current' | 'future'
                        },
                        ...
                    ]
                }
            ]
        }
    """
    result = {"code": tax_code, "name": tax_name, "sections": [], "exemptions": []}

    # Combine all pages into one stream of lines, removing page break markers
    # and deduplicating lines that appear in overlapping page captures
    all_lines = []
    seen_lines = set()

    for line in raw_text.split("\n"):
        stripped = line.strip()
        if stripped == "--- PAGE BREAK ---":
            continue
        if not stripped:
            continue
        # Deduplicate: skip lines we've already seen, unless they're rate lines.
        # Both fixed-amount lines AND percent-rate lines can repeat legitimately
        # (e.g. "15 PERCENT ON P7..." appears in both TAX RATE and EXEMPTIONS).
        amount_match_check = _RE_AMOUNT_CHECK.search(stripped)
        pct_match_check = _RE_PERCENT.match(stripped)
        line_key = stripped.rstrip()
        if not amount_match_check and not pct_match_check and line_key in seen_lines:
            continue
        seen_lines.add(line_key)
        all_lines.append(stripped)

    in_tax_rate = False
    seen_tax_rate_block = False
    current_category = ""
    current_subcategory = ""
    current_rates = []
    pending_condition = ""       # "... AND" multi-line continuation
    last_condition_prefix = ""   # standalone date-condition line preceding percent rates

    in_exemptions = False
    current_exempt_pax = ""      # "INFANTS", "CHILDREN", "ADULTS"
    current_exempt_rates: list = []

    # Amount pattern: e.g. "SGD 46.40", "CNY 172", "AED 75"
    amount_pattern = _RE_AMOUNT

    # PAX type keywords that introduce an exemption sub-section
    _PAX_KEYWORDS = ("INFANTS", "CHILDREN", "ADULTS")

    def _extract_basis_code(desc: str) -> Optional[str]:
        """Pull the IATA tax code from a percent-rate description."""
        m = _RE_BASIS_CODE_TRAILING.search(desc)
        if m:
            return m.group(1)
        m = _RE_BASIS_CODE_EMBEDDED.search(desc)
        return m.group(1) if m else None

    def _append_percent_rate(
        rate_list: list,
        pct: float,
        basis_code: Optional[str],
        condition: str,
    ) -> None:
        """Add a percent rate, grouping consecutive lines with the same condition."""
        if (
            rate_list
            and rate_list[-1].get("percent") == pct
            and rate_list[-1].get("condition") == condition
            and rate_list[-1].get("currency") is None
        ):
            # Same rate block — append basis code to existing entry
            if basis_code and basis_code not in rate_list[-1]["basis_codes"]:
                rate_list[-1]["basis_codes"].append(basis_code)
        else:
            rate_list.append(
                {
                    "condition": condition,
                    "currency": None,
                    "amount": None,
                    "percent": pct,
                    "basis_codes": [basis_code] if basis_code else [],
                    "status": _determine_status(condition),
                }
            )

    for i, stripped in enumerate(all_lines):
        upper = stripped.upper()

        # ── EXEMPTIONS section ──────────────────────────────────────────────
        if upper.startswith("EXEMPTIONS"):
            if seen_tax_rate_block:
                if current_rates:
                    result["sections"].append(
                        {
                            "category": current_category,
                            "subcategory": current_subcategory,
                            "rates": current_rates,
                        }
                    )
                    current_rates = []
                in_tax_rate = False
                in_exemptions = True
                last_condition_prefix = ""
            continue

        # ── Parse inside EXEMPTIONS ─────────────────────────────────────────
        if in_exemptions:
            if upper in ("END", "MD", ")>", ">", "", "."):
                continue
            # New pax-type sub-section
            for pax in _PAX_KEYWORDS:
                if pax in upper:
                    if current_exempt_rates:
                        result["exemptions"].append(
                            {"pax_type": current_exempt_pax, "rates": current_exempt_rates}
                        )
                    current_exempt_pax = pax
                    current_exempt_rates = []
                    last_condition_prefix = ""
                    break
            # Percent rate in exemption
            pct_m = _RE_PERCENT.match(stripped)
            if pct_m:
                pct = float(pct_m.group(1))
                desc = pct_m.group(2).strip().rstrip(".")
                basis_code = _extract_basis_code(desc)
                condition = last_condition_prefix
                if pending_condition:
                    condition = f"{pending_condition} {condition}".strip()
                    pending_condition = ""
                _append_percent_rate(current_exempt_rates, pct, basis_code, condition)
            elif upper.endswith("AND"):
                pending_condition = _RE_LEADING_DASH.sub("", stripped).strip()
            elif _RE_DATE_COND.search(stripped) and not amount_pattern.search(stripped):
                last_condition_prefix = _RE_LEADING_DASH.sub("", stripped).strip()
            continue

        # ── Detect TAX RATE section header ──────────────────────────────────
        header_patterns = [
            "TAX RATE",
            "TAX RATES",
            "TAX ASSESSMENT",
            "TAXES APPLY",
            "TAX INFORMATION",
        ]
        if any(h in upper for h in header_patterns) and not amount_pattern.search(stripped):
            in_tax_rate = True
            seen_tax_rate_block = True
            continue

        # Fallback: auto-trigger on a valid amount line when header was absent
        if not in_tax_rate and amount_pattern.search(stripped):
            if not any(upper.startswith(p) for p in ["FTAX", "MD", "END", "FARE"]):
                in_tax_rate = True
                seen_tax_rate_block = True

        if not in_tax_rate:
            if not result["name"] and result["code"]:
                name_match = re.search(
                    rf'{re.escape(result["code"])}\s*[-–]\s+(.+)', stripped
                )
                if name_match:
                    result["name"] = name_match.group(1).strip()
            continue

        # ── Inside TAX RATE block ───────────────────────────────────────────
        if upper in ("END", "MD", ")>", ">", "", "."):
            continue
        if upper.startswith("FTAX"):
            continue
        if upper == "INVALID":
            continue
        if any(
            upper.startswith(prefix)
            for prefix in [
                "TAX CODE:",
                "TAX DEFINITION:",
                "TAX SPECIAL:",
                "TAX COMMENTS:",
                "TAX APPLICATION:",
                "NAME OF COUNTRY:",
                "NAME OF TAX:",
                "***",
                "//1A.",
            ]
        ):
            continue

        amount_match = amount_pattern.search(stripped)

        if amount_match:
            currency = amount_match.group(1)
            amount = float(amount_match.group(2))
            condition_text = stripped[: amount_match.start()].strip()
            if pending_condition:
                condition_text = f"{pending_condition} {condition_text}"
                pending_condition = ""
            condition_text = _RE_LEADING_DASH.sub("", condition_text).strip()
            status = _determine_status(condition_text)
            current_rates.append(
                {
                    "condition": condition_text,
                    "currency": currency,
                    "amount": amount,
                    "status": status,
                }
            )
            last_condition_prefix = ""  # reset once a rate is consumed

        elif _RE_PERCENT.match(stripped):
            # Percent-based rate: "15 PERCENT ON EMBARKATION FEE - BD"
            pct_m = _RE_PERCENT.match(stripped)
            pct = float(pct_m.group(1))
            desc = pct_m.group(2).strip().rstrip(".")
            basis_code = _extract_basis_code(desc)
            condition = last_condition_prefix
            if pending_condition:
                condition = f"{pending_condition} {condition}".strip()
                pending_condition = ""
            _append_percent_rate(current_rates, pct, basis_code, condition)
            # Keep last_condition_prefix — next percent line in same block reuses it

        elif upper.endswith("AND"):
            text = _RE_LEADING_DASH.sub("", stripped).strip()
            pending_condition = text

        elif _RE_DATE_COND.search(stripped) and not amount_match:
            # Standalone date-condition line preceding percent rates
            last_condition_prefix = _RE_LEADING_DASH.sub("", stripped).strip()

        elif _is_category_line(stripped):
            if current_rates:
                result["sections"].append(
                    {
                        "category": current_category,
                        "subcategory": current_subcategory,
                        "rates": current_rates,
                    }
                )
                current_rates = []
            last_condition_prefix = ""
            if _is_main_category(stripped):
                current_category = stripped
                current_subcategory = ""
            else:
                current_subcategory = stripped

    # ── Flush final buffers ─────────────────────────────────────────────────
    if current_rates:
        result["sections"].append(
            {
                "category": current_category,
                "subcategory": current_subcategory,
                "rates": current_rates,
            }
        )
    if current_exempt_rates:
        result["exemptions"].append(
            {"pax_type": current_exempt_pax, "rates": current_exempt_rates}
        )

    # Debug logging if nothing was extracted
    if not result["sections"]:
        logger.warning(
            f"    parse_ftax_detail: 0 sections for {tax_code}. "
            f"in_tax_rate reached: {in_tax_rate}, "
            f"total lines processed: {len(all_lines)}"
        )
        if all_lines:
            logger.debug(f"    First 10 lines: {all_lines[:10]}")

    return result


def _is_category_line(line: str) -> bool:
    """Check if a line is a category/subcategory header (no amount, descriptive text)."""
    upper = line.strip().upper()

    # Skip very short lines or noise
    if len(upper) < 3:
        return False

    # Airport code pattern: "SIN - CHANGI", "XSP", "SELETAR XSP"
    if _RE_AIRPORT_CODE.match(upper):
        return True

    # Category indicators (Global coverage)
    category_keywords = [
        "DEPARTURES",
        "ARRIVALS",
        "INTERNATIONAL",
        "DOMESTIC",
        "TERMINAL",
        "TRANSIT",
        "TRANSFER",
        "PASSENGER",
        "ADULTS",
        "CHILDREN",
        "INFANTS",
        "PERSON",
        "FLIGHTS",
        "EMBARKATION",
        "APPLICABLE",
        "EXEMPT",
        "EXCEPT",
        "SELETAR",
        "CHANGI",
        "REPUBLIC",
        "KINGDOM",
        "STATE",
    ]

    # Must contain a keyword and NOT contain an amount at the end
    has_keyword = any(kw in upper for kw in category_keywords)
    has_amount = bool(_RE_HAS_AMOUNT.search(upper))

    return has_keyword and not has_amount


def _is_main_category(line: str) -> bool:
    """Check if this is a top-level category (e.g., DEPARTURES FROM CHANGI SIN)."""
    upper = line.strip().upper()
    # Airport code pattern like "SIN - CHANGI" is a main location
    if _RE_AIRPORT_CODE.match(upper):
        return True
    return (
        "DEPARTURES FROM" in upper
        or "ARRIVALS AT" in upper
        or "DEPARTURES" == upper
        or "ARRIVALS" == upper
    )


def _determine_status(condition: str, reference_date: datetime = None) -> str:
    """
    Determine if a tax rate is expired, current, or future based on
    date conditions in the text.

    Examples:
        "TKT ON/BEFORE 31MAR25"          → expired (past date)
        "TVL ON/AFTER 01APR25 AND ON/BEFORE 31MAR27" → current (includes today)
        "TVL ON/AFTER 01APR29"            → future

    reference_date: override today's date (useful for testing).
    """
    today = reference_date if reference_date is not None else datetime.now()

    # Extract all dates from the condition
    dates = []
    for match in _RE_DATE.finditer(condition.upper()):
        day = int(match.group(1))
        month_str = match.group(2)
        year_str = match.group(3)

        month_map = {
            "JAN": 1,
            "FEB": 2,
            "MAR": 3,
            "APR": 4,
            "MAY": 5,
            "JUN": 6,
            "JUL": 7,
            "AUG": 8,
            "SEP": 9,
            "OCT": 10,
            "NOV": 11,
            "DEC": 12,
        }

        month = month_map.get(month_str)
        if not month:
            continue

        year = int(year_str)
        if year < 100:
            # 2-digit year: assume 2000s, but cap at current_year+20 to
            # avoid treating legacy dates like "99" as 2099 instead of 1999
            current_year = today.year
            year += 2000
            if year > current_year + 20:
                year -= 100

        try:
            dates.append(datetime(year, month, day))
        except ValueError:
            continue

    if not dates:
        return "current"  # No dates = always applicable

    upper_cond = condition.upper()

    if "ON/BEFORE" in upper_cond and "ON/AFTER" not in upper_cond:
        # Pure "on/before" → expired if the date is past
        end_date = max(dates)
        return "expired" if today > end_date else "current"

    if "ON/AFTER" in upper_cond and "ON/BEFORE" not in upper_cond:
        # Pure "on/after" → future if start date is in the future
        start_date = min(dates)
        return "future" if today < start_date else "current"

    if "ON/AFTER" in upper_cond and "ON/BEFORE" in upper_cond:
        # Range: on/after X and on/before Y
        start_date = min(dates)
        end_date = max(dates)
        if today < start_date:
            return "future"
        elif today > end_date:
            return "expired"
        else:
            return "current"

    return "current"


def get_current_rate(sections: list[dict]) -> Optional[dict]:
    """
    From a list of sections, find the currently applicable rate.
    Returns the first rate with status='current', or None.
    """
    for section in sections:
        for rate in section.get("rates", []):
            if rate.get("status") == "current":
                return rate
    return None


def get_next_rate(sections: list[dict]) -> Optional[dict]:
    """
    From a list of sections, find the next upcoming rate change.
    Returns the first rate with status='future', or None.
    """
    for section in sections:
        for rate in section.get("rates", []):
            if rate.get("status") == "future":
                return rate
    return None


if __name__ == "__main__":
    # Quick test with sample FTAX output
    sample_list = """
THE FOLLOWING TAX ASSESSMENTS APPLY TO SINGAPORE:
AIRPORT DEVELOPMENT LEVY                >FTAX-SG/L7·
AVIATION LEVY                           >FTAX-SG/OP·
PASSENGER SERVICE CHARGE                >FTAX-SG/SG·
    """

    print("=== Tax type list ===")
    types = parse_ftax_list(sample_list)
    for t in types:
        print(f"  {t['code']}: {t['name']} ({t['airports']})")

    sample_detail = """
FTAX-SG/L7
L7 - AIRPORT DEVELOPMENT LEVY
TAX RATE
    DEPARTURES FROM CHANGI SIN
    INTERNATIONAL DEPARTURES FROM
    TERMINAL 1 2 3
    -TKT/TVL ON/BEFORE 31MAR25              SGD 46.40
    -TKT ON/AFTER 01JAN25 AND
     TVL ON/AFTER 01APR25 AND
     ON/BEFORE 31MAR27                       SGD 46.40
    TLV ON/AFTER 01APR27 AND
     ON/BEFORE 31MAR28                       SGD 49.40
    TVL ON/AFTER 01APR28 AND
     ON/BEFORE 31MAR29                       SGD 52.40
    TVL ON/AFTER 01APR29 AND
END
    """

    print("\n=== Tax detail ===")
    detail = parse_ftax_detail(sample_detail, "L7", "AIRPORT DEVELOPMENT LEVY")
    for section in detail["sections"]:
        print(f"  Category: {section['category']}")
        print(f"  Subcategory: {section['subcategory']}")
        for rate in section["rates"]:
            print(
                f"    {rate['condition']} → {rate['currency']} {rate['amount']} [{rate['status']}]"
            )
