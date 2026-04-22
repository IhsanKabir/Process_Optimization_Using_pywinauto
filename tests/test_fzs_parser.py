"""Tests for fzs_parser.parse_fzs_output.

Covers the precision contract requested by the user: the parser must preserve
the exact rate emitted by the terminal (e.g. ``33.760812``) instead of rounding
to a fixed number of decimals.
"""
import pytest

from fzs_parser import parse_fzs_output


@pytest.mark.unit
def test_preserves_six_decimal_rate_from_bank_selling_line() -> None:
    raw = (
        ">FZSQAR1BDT\n"
        "RATES LAST UPDATED 21APR 16:00 PM\n"
        "EQU BDT34\n"
        "BANK SELLING RATE  1QAR EQUALS  33.760812   BDT\n"
        ">\n"
    )

    result = parse_fzs_output(raw, "QAR", "BDT")

    assert result["rate"] == pytest.approx(33.760812, rel=0, abs=1e-9)


@pytest.mark.unit
def test_preserves_subunit_rate() -> None:
    raw = "BANK SELLING RATE  1LKR EQUALS  0.385054   BDT\n"

    result = parse_fzs_output(raw, "LKR", "BDT")

    assert result["rate"] == pytest.approx(0.385054, rel=0, abs=1e-9)


@pytest.mark.unit
def test_inverse_direction_preserves_precision() -> None:
    # Terminal printed the reverse direction; parser should invert and keep
    # full precision.
    raw = "BANK SELLING RATE  33.760812 BDT EQUALS  1 QAR\n"

    result = parse_fzs_output(raw, "QAR", "BDT")

    assert result["rate"] == pytest.approx(33.760812, rel=0, abs=1e-9)


@pytest.mark.unit
def test_rejects_error_screens() -> None:
    raw = "CHECK FORMAT\n"

    result = parse_fzs_output(raw, "USD", "BDT")

    assert result["rate"] == 0.0
