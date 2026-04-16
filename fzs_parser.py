"""
fzs_parser.py - FZS Currency Conversion Output Parser

Parses raw text output from Travelport Smartpoint FZS commands
into structured exchange rate data.

Command format:
  FZSUSD1BDT/   → Convert 1 USD to BDT
  FZSGBP1BDT/   → Convert 1 GBP to BDT

Expected output format (varies, but typically contains):
  BSR  1USD = 122.7100 BDT
  or similar rate display lines.
"""

import re
import logging
from typing import Optional

logger = logging.getLogger("travelport.fzs_parser")

# Patterns to extract rate from FZS output
# Matches: "1USD = 122.7100 BDT" or "BSR 1.00USD = 122.71BDT"
_RE_RATE = re.compile(
    r"(\d+\.?\d*)\s*([A-Z]{3})\s*=\s*(\d+\.?\d*)\s*([A-Z]{3})"
)
# Also try: "RATE: 122.7100" or similar
_RE_RATE_SIMPLE = re.compile(r"RATE\s*:?\s*(\d+\.?\d*)")
# Also: "BSR 122.7100" (Bank Selling Rate)
_RE_BSR = re.compile(r"BSR\s+(\d+\.?\d*)")
# NUC rate line
_RE_NUC = re.compile(r"ROE\s*(\d+\.?\d*)")


def parse_fzs_output(
    text: str, from_currency: str, to_currency: str
) -> dict:
    """
    Parse FZS command output to extract exchange rate.

    Returns:
        dict with keys: from_currency, to_currency, rate, raw_text
    """
    result = {
        "from_currency": from_currency,
        "to_currency": to_currency,
        "rate": 0.0,
        "raw_text": text.strip()[:200],
    }

    if not text or not text.strip():
        return result

    # Try the full equation pattern first: "1USD = 122.71BDT"
    for match in _RE_RATE.finditer(text):
        src_amt = float(match.group(1))
        src_cur = match.group(2)
        dst_amt = float(match.group(3))
        dst_cur = match.group(4)

        if src_cur == from_currency and dst_cur == to_currency and src_amt > 0:
            result["rate"] = round(dst_amt / src_amt, 4)
            return result
        if src_cur == to_currency and dst_cur == from_currency and dst_amt > 0:
            result["rate"] = round(src_amt / dst_amt, 4)
            return result

    # Fallback: BSR line
    bsr_match = _RE_BSR.search(text)
    if bsr_match:
        result["rate"] = float(bsr_match.group(1))
        return result

    # Fallback: simple RATE line
    rate_match = _RE_RATE_SIMPLE.search(text)
    if rate_match:
        result["rate"] = float(rate_match.group(1))
        return result

    # Fallback: ROE
    roe_match = _RE_NUC.search(text)
    if roe_match:
        result["rate"] = float(roe_match.group(1))
        return result

    logger.warning(
        f"  Could not parse FZS rate from output for {from_currency}->{to_currency}"
    )
    return result
