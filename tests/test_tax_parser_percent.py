"""Tests for percent-based rate parsing and exemption parsing in tax_parser."""
import pytest
from tax_parser import parse_ftax_detail

# ── helpers ──────────────────────────────────────────────────────────────────

def _parse(raw: str, code: str = "E5") -> dict:
    return parse_ftax_detail(raw, code, "VALUE ADDED TAX ON EMBARKATION FEES")


def _rates(result: dict, section_idx: int = 0) -> list:
    return result["sections"][section_idx]["rates"]


# ── percent rate in TAX RATE block ───────────────────────────────────────────

FTAX_E5_SIMPLE = """
VALUE ADDED TAX ON EMBARKATION FEES

TAX RATE:
     TKT ON/BEFORE 15AUG20
     15 PERCENT OF APPLICABLE EMBARKATION -BD- FEE.
     TKT/TVL ON/AFTER 16AUG20
     15 PERCENT ON EMBARKATION FEE  - BD
     15 PERCENT ON AIRPORT DEVELOPMENT FEE - P7
     15 PERCENT ON PASSENGER SECURITY FEE - P8
"""


def test_percent_rates_parsed():
    result = _parse(FTAX_E5_SIMPLE)
    assert result["sections"], "Expected at least one section"
    rates = _rates(result)
    assert len(rates) == 2, f"Expected 2 rate entries (old+new), got {rates}"


def test_old_rate_bd_only():
    result = _parse(FTAX_E5_SIMPLE)
    old_rate = _rates(result)[0]
    assert old_rate["percent"] == 15.0
    assert old_rate["basis_codes"] == ["BD"]
    assert old_rate["currency"] is None
    assert old_rate["amount"] is None


def test_new_rate_bd_p7_p8_grouped():
    result = _parse(FTAX_E5_SIMPLE)
    new_rate = _rates(result)[1]
    assert new_rate["percent"] == 15.0
    assert set(new_rate["basis_codes"]) == {"BD", "P7", "P8"}


def test_old_rate_condition_captured():
    result = _parse(FTAX_E5_SIMPLE)
    old_rate = _rates(result)[0]
    assert "15AUG20" in old_rate["condition"], f"Condition: {old_rate['condition']!r}"


def test_new_rate_condition_captured():
    result = _parse(FTAX_E5_SIMPLE)
    new_rate = _rates(result)[1]
    assert "16AUG20" in new_rate["condition"], f"Condition: {new_rate['condition']!r}"


# ── exemptions section ───────────────────────────────────────────────────────

FTAX_E5_WITH_EXEMPTION = """
VALUE ADDED TAX ON EMBARKATION FEES

TAX RATE:
     TKT/TVL ON/AFTER 16AUG20
     15 PERCENT ON EMBARKATION FEE  - BD
     15 PERCENT ON AIRPORT DEVELOPMENT FEE - P7
     15 PERCENT ON PASSENGER SECURITY FEE - P8

EXEMPTIONS:
     INFANTS
     15 PERCENT ON AIRPORT DEVELOPMENT FEE - P7
     15 PERCENT ON PASSENGER SECURITY FEE - P8
"""


def test_exemptions_parsed():
    result = _parse(FTAX_E5_WITH_EXEMPTION)
    assert result["exemptions"], "Expected exemptions list to be populated"


def test_infant_exemption_pax_type():
    result = _parse(FTAX_E5_WITH_EXEMPTION)
    assert result["exemptions"][0]["pax_type"] == "INFANTS"


def test_infant_exemption_p7_p8_only():
    result = _parse(FTAX_E5_WITH_EXEMPTION)
    infant_rates = result["exemptions"][0]["rates"]
    assert len(infant_rates) == 1
    codes = set(infant_rates[0]["basis_codes"])
    assert codes == {"P7", "P8"}, f"Expected P7+P8, got {codes}"
    assert "BD" not in codes, "BD should NOT appear in infant exemption rates"


def test_exemption_does_not_bleed_into_sections():
    result = _parse(FTAX_E5_WITH_EXEMPTION)
    # Main section should only contain the adult rates (BD+P7+P8), not the infant ones
    main_codes = set(result["sections"][0]["rates"][0]["basis_codes"])
    assert "BD" in main_codes  # adult rate includes BD
