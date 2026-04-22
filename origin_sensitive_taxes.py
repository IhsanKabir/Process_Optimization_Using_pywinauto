"""Adjustments for taxes that only apply when a journey originates in a
specific country.

Some IATA tax codes (notably India's K3) are levied only on journeys that
depart from that country. Our FS extraction scrapes each direction of a
round-trip as a standalone one-way, so the *inbound* one-way scrape will
include such a tax even when the actual round-trip journey doesn't start
there — producing a phantom charge when we sum the two legs.

This module compensates for that artifact by stripping origin-sensitive
codes from the RT total when the outbound origin doesn't match the tax's
required country.
"""
from __future__ import annotations

import logging
from functools import lru_cache

try:
    import airportsdata
except ImportError:  # pragma: no cover — packaged dependency, exercised in tests via fallback
    airportsdata = None  # type: ignore[assignment]

logger = logging.getLogger("travelport.origin_sensitive_taxes")

# IATA tax code → ISO country code that the journey must originate from for
# the tax to legitimately apply. Extend this when new origin-sensitive taxes
# come up (e.g. certain GCC or EU codes).
ORIGIN_SENSITIVE_TAX_CODES: dict[str, str] = {
    "K3": "IN",  # India GST on air travel — applies only on departures from India
}


@lru_cache(maxsize=8)
def _airports_in_country(country_code: str) -> frozenset[str]:
    """Return the set of IATA codes for airports in ``country_code``.

    Cached per country so we don't re-scan the full IATA dataset on every
    round-trip row. Returns an empty frozenset if ``airportsdata`` isn't
    available — the caller should treat that as "no phantom stripping," which
    is safe for the happy path (the unstripped sum matches reality when both
    ends are in the same country as the tax origin).
    """
    if airportsdata is None:
        logger.debug(
            "airportsdata unavailable; cannot resolve %s airports — "
            "origin-sensitive tax stripping disabled.",
            country_code,
        )
        return frozenset()

    country_upper = country_code.upper().strip()
    codes: set[str] = set()
    for airport_code, airport_info in airportsdata.load("IATA").items():
        country = str(airport_info.get("country", "") or "").upper().strip()
        if country == country_upper:
            normalized = str(airport_code or "").upper().strip()
            if normalized:
                codes.add(normalized)
    return frozenset(codes)


def _k3_from_breakdown(fs_taxes: dict, tax_code: str) -> float:
    """Extract a single tax code's BDT value from an ``fs_taxes`` dict."""
    breakdown = fs_taxes.get("tax_breakdown") or {}
    try:
        return float(breakdown.get(tax_code, 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def compute_rt_tax_total(
    outbound_origin: str,
    outbound_fs_taxes: dict | None,
    inbound_fs_taxes: dict | None,
) -> float:
    """Compute the BDT tax total for a round-trip journey.

    Starts from ``tax_ow + tax_in`` (the natural sum of the two one-way FS
    scrapes) and strips any origin-sensitive tax that only applies when the
    outbound origin matches the tax's required country.

    Parameters
    ----------
    outbound_origin:
        IATA code of the RT journey's first departure airport.
    outbound_fs_taxes / inbound_fs_taxes:
        The ``fs_taxes`` dict produced by ``tax_breakdown_parser``. Either
        may be empty/``None``.
    """
    out_fs = outbound_fs_taxes or {}
    in_fs = inbound_fs_taxes or {}

    tax_rt = float(out_fs.get("total_taxes", 0) or 0) + float(
        in_fs.get("total_taxes", 0) or 0
    )

    origin = (outbound_origin or "").upper().strip()
    if not origin:
        return tax_rt

    for tax_code, required_country in ORIGIN_SENSITIVE_TAX_CODES.items():
        if origin in _airports_in_country(required_country):
            # Origin matches the tax's country — whatever each leg reports
            # is legitimate; nothing to strip.
            continue

        phantom = _k3_from_breakdown(out_fs, tax_code) + _k3_from_breakdown(
            in_fs, tax_code
        )
        if phantom:
            logger.debug(
                "Stripping phantom %s=%.2f BDT from RT total "
                "(outbound origin %s is not in %s).",
                tax_code,
                phantom,
                origin,
                required_country,
            )
            tax_rt -= phantom

    return tax_rt
