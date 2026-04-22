"""Tests for the origin-sensitive tax compensation layer.

Context: some IATA tax codes (notably India K3) are levied only on journeys
that depart from that country. Our FS scrapes collect each direction as an
isolated one-way, so the inbound scrape of a non-India→India→non-India
round-trip will include a phantom K3 that the actual RT journey wouldn't
incur. These tests pin that behaviour down.
"""
from __future__ import annotations

import pytest

from origin_sensitive_taxes import (
    ORIGIN_SENSITIVE_TAX_CODES,
    _airports_in_country,
    compute_rt_tax_total,
)


# Scrape fixtures modelled on real Travelport output. Values match the
# examples the user shared for DAC↔CCU.
OUT_DAC_CCU = {
    "total_taxes": 9416.0,
    "tax_breakdown": {
        "BD": 500, "OW": 1000, "P7": 615, "P8": 738, "UT": 2000,
        "IN": 2052, "P2": 1741, "E5": 278,
    },
}
IN_CCU_DAC = {
    "total_taxes": 9837.0,
    "tax_breakdown": {
        "BD": 500, "OW": 1000, "P7": 615, "P8": 738, "UT": 2000,
        "IN": 2052, "K3": 421, "P2": 1741, "E5": 278,
    },
}


@pytest.mark.unit
def test_non_india_origin_strips_phantom_k3_from_inbound() -> None:
    # DAC-CCU-DAC: origin is Bangladesh. Inbound one-way (CCU→DAC) scraped in
    # isolation bills K3=421 as if the return leg were a standalone India
    # departure — it isn't, so it must come off the RT total.
    total = compute_rt_tax_total("DAC", OUT_DAC_CCU, IN_CCU_DAC)

    assert total == pytest.approx(9416.0 + 9837.0 - 421.0)


@pytest.mark.unit
def test_india_origin_keeps_k3() -> None:
    # CCU-DAC-CCU: origin IS India, so the K3 on the outbound (CCU→DAC) is
    # legitimate and the inbound (DAC→CCU) has no K3 of its own. Simple sum.
    out_ccu_dac = IN_CCU_DAC           # outbound from India has K3
    in_dac_ccu = dict(OUT_DAC_CCU)     # inbound from BD has no K3

    total = compute_rt_tax_total("CCU", out_ccu_dac, in_dac_ccu)

    assert total == pytest.approx(9837.0 + 9416.0)


@pytest.mark.unit
@pytest.mark.parametrize("iata", ["DEL", "BOM", "MAA", "BLR", "HYD"])
def test_any_indian_airport_keeps_k3(iata: str) -> None:
    out_with_k3 = {"total_taxes": 5000, "tax_breakdown": {"K3": 250}}
    in_no_k3 = {"total_taxes": 3000, "tax_breakdown": {}}

    total = compute_rt_tax_total(iata, out_with_k3, in_no_k3)

    assert total == pytest.approx(8000.0)


@pytest.mark.unit
def test_origin_is_case_insensitive() -> None:
    assert compute_rt_tax_total("ccu", IN_CCU_DAC, OUT_DAC_CCU) == pytest.approx(
        compute_rt_tax_total("CCU", IN_CCU_DAC, OUT_DAC_CCU)
    )


@pytest.mark.unit
def test_empty_legs_return_zero() -> None:
    assert compute_rt_tax_total("DAC", {}, {}) == 0.0


@pytest.mark.unit
def test_none_legs_return_zero() -> None:
    assert compute_rt_tax_total("DAC", None, None) == 0.0


@pytest.mark.unit
def test_missing_origin_returns_uncorrected_sum() -> None:
    # Without an origin we can't decide whether to strip; fall back to the
    # naive sum so we never silently under-count.
    total = compute_rt_tax_total("", OUT_DAC_CCU, IN_CCU_DAC)

    assert total == pytest.approx(9416.0 + 9837.0)


@pytest.mark.unit
def test_malformed_tax_breakdown_is_safe() -> None:
    weird = {
        "total_taxes": 100.0,
        "tax_breakdown": {"K3": "not-a-number"},
    }
    total = compute_rt_tax_total("DAC", {"total_taxes": 50.0}, weird)

    # K3 can't be parsed → treated as 0, nothing stripped.
    assert total == pytest.approx(150.0)


@pytest.mark.unit
def test_k3_is_currently_the_only_origin_sensitive_code() -> None:
    # If this fails, someone added a new code. Update the test and confirm
    # the compute_rt_tax_total logic still covers the new case.
    assert ORIGIN_SENSITIVE_TAX_CODES == {"K3": "IN"}


@pytest.mark.unit
def test_india_airport_set_is_populated() -> None:
    indian = _airports_in_country("IN")
    # Sanity check a handful of well-known IATA codes. Frozen so the lookup
    # stays O(1).
    for iata in ("DEL", "BOM", "CCU", "MAA"):
        assert iata in indian
    # And guard against false positives.
    for iata in ("DAC", "DOH", "DXB"):
        assert iata not in indian
