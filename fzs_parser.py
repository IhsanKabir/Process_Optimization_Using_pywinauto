"""
fzs_parser.py - FZS Currency Conversion Output Parser

Parses raw text output from Travelport Smartpoint FZS commands
into structured exchange rate data.

Command format:
  FZSUSD1BDT   → Convert 1 USD to BDT
  FZSGBP1BDT   → Convert 1 GBP to BDT

Expected output format (varies, but typically contains):
  BSR  1USD = 122.7100 BDT
  or similar rate display lines.
"""

import re
import logging
from typing import Optional

logger = logging.getLogger("travelport.fzs_parser")

# Patterns to extract rate from FZS output
# Strict: "1USD = 122.7100 BDT" — requires the exact currency codes we asked for.
_RE_RATE = re.compile(
    r"(\d+(?:\.\d+)?)\s*([A-Z]{3})\s*=\s*(\d+(?:\.\d+)?)\s*([A-Z]{3})"
)
# Error markers Travelport emits when a command is malformed/unsupported.
_ERROR_MARKERS = (
    "CHECK FORMAT",
    "INVALID FORMAT",
    "NOT PROCESSED",
    "UNABLE",
    "INVALID COMMAND",
    "FORMAT ERROR",
)


def parse_fzs_output(
    text: str, from_currency: str, to_currency: str
) -> dict:
    """
    Parse FZS command output to extract exchange rate.

    Only accepts an exact `<amt> <FROM> = <amt> <TO>` match (or the inverse
    direction). Refuses to guess from loose RATE/BSR/ROE lines because those
    match noise in error screens and produce bogus 1.0 rates.

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

    upper_text = text.upper()
    if any(marker in upper_text for marker in _ERROR_MARKERS):
        logger.warning(
            f"  FZS command rejected by Travelport for {from_currency}->{to_currency}"
        )
        return result

    for match in _RE_RATE.finditer(upper_text):
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

    logger.warning(
        f"  Could not parse FZS rate from output for {from_currency}->{to_currency}"
    )
    return result
