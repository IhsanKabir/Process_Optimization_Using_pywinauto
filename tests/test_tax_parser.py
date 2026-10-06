"""Tests for tax_parser using line formats taken from real FTAX captures."""

from datetime import datetime

import pytest

from tax_parser import (
    _determine_status,
    get_current_rate,
    get_next_rate,
    parse_ftax_detail,
    parse_ftax_list,
)


def _all_rates(result: dict) -> list:
    return [rate for section in result["sections"] for rate in section["rates"]]


# ── parse_ftax_list ───────────────────────────────────────────────────────────

FTAX_AE_LIST = """
FTAX-AE
>**************************************************************
                       UNITED ARAB EMIRATES
****************************************************************
    THE FOLLOWING TAX ASSESSMENTS APPLY TO UNITED ARAB EMIRATES:
PASSENGER SERVICE CHARGE                >FTAX-AE/AE·
PASSENGER FACILITIES CHARGE             >FTAX-AE/F6·
PASSENGER SECURITY AND SAFETY FEE       >FTAX-AE/TP·
INTERNATIONAL ADVANCED PASSENGER IN     >FTAX-AE/ZR·
>
"""


def test_parse_ftax_list_extracts_codes_and_names():
    types = parse_ftax_list(FTAX_AE_LIST)

    assert [t["code"] for t in types] == ["AE", "F6", "TP", "ZR"]
    assert types[1]["name"] == "PASSENGER FACILITIES CHARGE"


def test_parse_ftax_list_ignores_text_without_links():
    assert parse_ftax_list("NO TAX DATA FOUND\n>") == []


# ── currency-first amounts (existing format) ─────────────────────────────────

FTAX_SG_L7 = """
L7 - AIRPORT DEVELOPMENT LEVY
TAX RATE
    DEPARTURES FROM CHANGI SIN
    INTERNATIONAL TERMINAL 1 2 3
    -TKT/TVL ON/BEFORE 31MAR25              SGD 46.40
    -TKT ON/AFTER 01JAN25 AND
     TVL ON/AFTER 01APR25                   SGD 49.40
END
"""


def test_currency_first_amounts_parsed():
    rates = _all_rates(parse_ftax_detail(FTAX_SG_L7, "L7"))

    assert [(r["currency"], r["amount"]) for r in rates] == [
        ("SGD", 46.40),
        ("SGD", 49.40),
    ]


def test_multiline_and_condition_is_joined():
    rates = _all_rates(parse_ftax_detail(FTAX_SG_L7, "L7"))

    assert rates[1]["condition"] == "TKT ON/AFTER 01JAN25 AND TVL ON/AFTER 01APR25"


def test_category_and_subcategory_captured():
    section = parse_ftax_detail(FTAX_SG_L7, "L7")["sections"][0]

    assert section["category"] == "DEPARTURES FROM CHANGI SIN"
    assert section["subcategory"] == "INTERNATIONAL TERMINAL 1 2 3"


def test_name_extracted_from_header_when_not_given():
    assert parse_ftax_detail(FTAX_SG_L7, "L7")["name"] == "AIRPORT DEVELOPMENT LEVY"


def test_duplicate_header_lines_across_pages_are_dropped():
    raw = FTAX_SG_L7.replace("END", "--- PAGE BREAK ---\nTAX RATE\nEND")

    assert len(_all_rates(parse_ftax_detail(raw, "L7"))) == 2


FTAX_SA_IO_NO_SPACE = """
TAX RATE:
     JED
     DEPARTURES                        SAR130.00
     RUH
     DEPARTURES                        SAR130.00
     RSI
     -TKT ON/AFTER 02MAY25 AND
      TVL ON/AFTER 01JUL25
     DEPARTURES                        SAR160.00
"""


def test_identical_unspaced_amounts_for_different_airports_are_kept():
    rates = _all_rates(parse_ftax_detail(FTAX_SA_IO_NO_SPACE, "IO"))

    assert [r["amount"] for r in rates] == [130.0, 130.0, 160.0]
    assert rates[2]["condition"].startswith("TKT ON/AFTER 02MAY25 AND")


def test_repeated_continuation_line_after_and_is_kept():
    raw = """
TAX RATE:
     JED
     -TKT ON/AFTER 17APR25 AND
      TVL ON/AFTER 01JUL25
     DEPARTURES                        SAR160.00
     RSI
     -TKT ON/AFTER 02MAY25 AND
      TVL ON/AFTER 01JUL25
     DEPARTURES                        SAR160.00
"""
    rates = _all_rates(parse_ftax_detail(raw, "IO"))

    assert [r["condition"] for r in rates] == [
        "TKT ON/AFTER 17APR25 AND TVL ON/AFTER 01JUL25 DEPARTURES",
        "TKT ON/AFTER 02MAY25 AND TVL ON/AFTER 01JUL25 DEPARTURES",
    ]


def test_three_line_and_condition_is_fully_joined():
    raw = """
TAX RATE:
     -TKT ON/AFTER 01JAN25 AND
      TVL ON/AFTER 01APR25 AND
          ON/BEFORE 31MAR27                   SGD 46.40
"""
    rates = _all_rates(parse_ftax_detail(raw, "SG"))

    assert rates[0]["condition"] == (
        "TKT ON/AFTER 01JAN25 AND TVL ON/AFTER 01APR25 AND ON/BEFORE 31MAR27"
    )


@pytest.mark.parametrize(
    "line",
    [
        "CHILDREN UNDER 12 YRS",
        "TKT ON/AFTER 01 JAN",
        "MAX 20 KGS",
        "TKT ISSUED WITHIN 24 HRS",
        "WITH A SEAT UNDER 2 AND",
    ],
)
def test_prose_ending_in_number_and_word_is_not_an_amount(line):
    raw = f"TAX RATE:\n     {line}\n     DEPARTURES                SGD 10.00\n"

    rates = _all_rates(parse_ftax_detail(raw, "XX"))

    assert [(r["currency"], r["amount"]) for r in rates] == [("SGD", 10.0)]


@pytest.mark.parametrize("line", ["SEE NOTE 5 PERCENT", "TAX 18 PERCENT."])
def test_prose_ending_in_percent_is_not_a_rate(line):
    raw = f"TAX RATE:\n     {line}\n"

    assert _all_rates(parse_ftax_detail(raw, "XX")) == []


# ── amount-first amounts (MY/H8, TH/AP, CN/AP, AE/F6 captures) ───────────────

FTAX_MY_H8 = """
TAX RATE:
     .
     TKT/TVL ON/AFTER 01MAY18
     ALL AIRPORTS
)>
--- PAGE BREAK ---
     INTERNATIONAL DEPARTURES                    1 MYR
     DOMESTIC DEPARTURES                         1 MYR
EXEMPTIONS:
     .
"""

FTAX_TH_AP = """
TAX RATE:
     .
     TAX RATE
)>
--- PAGE BREAK ---
     DEPARTURES                             4.00 USD
EXEMPTIONS:
     .
"""

FTAX_AE_F6 = """
TAX RATE:
     .
     AI TAX EXCEPTION
     DEPARTURES
     WHEN AI IS THE OPERATING CARRIER
     RKT                               45AED
TAX SPECIAL:
     .
"""


def test_amount_first_with_space_parsed():
    rates = _all_rates(parse_ftax_detail(FTAX_MY_H8, "H8"))

    assert [(r["currency"], r["amount"]) for r in rates] == [("MYR", 1.0), ("MYR", 1.0)]
    assert rates[0]["condition"] == "INTERNATIONAL DEPARTURES"


def test_amount_first_with_decimal_parsed():
    rates = _all_rates(parse_ftax_detail(FTAX_TH_AP, "AP"))

    assert len(rates) == 1
    assert (rates[0]["currency"], rates[0]["amount"]) == ("USD", 4.0)
    assert rates[0]["condition"] == "DEPARTURES"


def test_amount_first_without_space_parsed():
    rates = _all_rates(parse_ftax_detail(FTAX_AE_F6, "F6"))

    assert len(rates) == 1
    assert (rates[0]["currency"], rates[0]["amount"]) == ("AED", 45.0)
    assert rates[0]["condition"] == "RKT"


def test_numbered_text_is_not_mistaken_for_amount():
    raw = "TAX RATE:\n     TERMINAL 1 2 3\n     SGD 10.80\n"

    rates = _all_rates(parse_ftax_detail(raw, "L7"))

    assert [(r["currency"], r["amount"]) for r in rates] == [("SGD", 10.80)]


# ── trailing percent (IN/K3, MY/D8, SA/K7 captures) ──────────────────────────

FTAX_MY_D8 = """
TAX RATE:
     .
     TVL ON/BEFORE 29FEB24                 6 PERCENT
     TKT/TVL ON/AFTER 01MAR24              8 PERCENT
EXEMPTIONS:
     .
     EXEMPTIONS
"""

FTAX_IN_K3 = """
     CARRIER BG TAX ON SERVICE FEES - TAX RATE
     ------------------------------------------
     0DG/0C1/0C3
     ECONOMY                     5 PERCENT
     PREMIUM ECONOMY            12 PERCENT
     BUSINESS                    5 PERCENT
"""

FTAX_SA_K7 = """
     TAX RATE
      - 5 PERCENT
     CARRIER IMPOSED -YQ/YR-
"""


def test_trailing_percent_with_date_condition():
    rates = _all_rates(parse_ftax_detail(FTAX_MY_D8, "D8"))

    assert [(r["percent"], r["condition"]) for r in rates] == [
        (6.0, "TVL ON/BEFORE 29FEB24"),
        (8.0, "TKT/TVL ON/AFTER 01MAR24"),
    ]
    assert rates[0]["status"] == "expired"


def test_trailing_percent_with_cabin_condition():
    rates = _all_rates(parse_ftax_detail(FTAX_IN_K3, "K3"))

    assert [(r["condition"], r["percent"]) for r in rates] == [
        ("ECONOMY", 5.0),
        ("PREMIUM ECONOMY", 12.0),
        ("BUSINESS", 5.0),
    ]
    assert all(r["currency"] is None and r["amount"] is None for r in rates)


def test_bare_dash_percent_has_empty_condition():
    rates = _all_rates(parse_ftax_detail(FTAX_SA_K7, "K7"))

    assert len(rates) == 1
    assert rates[0]["percent"] == 5.0
    assert rates[0]["condition"] == ""


# ── _determine_status ─────────────────────────────────────────────────────────

REF = datetime(2026, 1, 15)


@pytest.mark.parametrize(
    "condition, expected",
    [
        ("TKT ON/BEFORE 31MAR25", "expired"),
        ("TKT ON/BEFORE 31MAR27", "current"),
        ("TVL ON/AFTER 01APR29", "future"),
        ("TVL ON/AFTER 01JAN25", "current"),
        ("TVL ON/AFTER 01APR25 AND ON/BEFORE 31MAR27", "current"),
        ("TVL ON/AFTER 01APR27 AND ON/BEFORE 31MAR28", "future"),
        ("TVL ON/AFTER 01APR23 AND ON/BEFORE 31MAR24", "expired"),
        ("DEPARTURES", "current"),
        ("TKT ON/BEFORE 31XYZ25", "current"),
        ("TKT ON/BEFORE 31DEC99", "expired"),
        ("TKT ON/BEFORE 31DEC2030", "current"),
    ],
)
def test_determine_status(condition, expected):
    assert _determine_status(condition, reference_date=REF) == expected


# ── get_current_rate / get_next_rate ──────────────────────────────────────────

SECTIONS = [
    {"rates": [{"status": "expired", "amount": 1}]},
    {"rates": [{"status": "current", "amount": 2}, {"status": "future", "amount": 3}]},
]


def test_get_current_rate_returns_first_current():
    assert get_current_rate(SECTIONS)["amount"] == 2


def test_get_next_rate_returns_first_future():
    assert get_next_rate(SECTIONS)["amount"] == 3


def test_rate_helpers_return_none_when_missing():
    assert get_current_rate([]) is None
    assert get_next_rate([{"rates": [{"status": "expired"}]}]) is None
