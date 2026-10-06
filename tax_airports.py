"""tax_airports.py - Resolve --tax --airport queries to tax airports.

Merges the global IATA directory (airportsdata), airport_country_codes and
tax_airports from config. See CLAUDE.md "Tax airport resolution".
"""

import os
import re
from functools import lru_cache

from exceptions import ValidationError
from validators import validate_airport_code, validate_route

try:
    import airportsdata
except ImportError:
    airportsdata = None


DEFAULT_AIRPORT_COUNTRY_CODES = {
    "DAC": "BD",
    "CGP": "BD",
    "ZYL": "BD",
    "CXB": "BD",
    "MLE": "MV",
    "CAN": "CN",
    "MCT": "OM",
    "DOH": "QA",
    "DXB": "AE",
    "AUH": "AE",
    "SHJ": "AE",
    "RKT": "AE",
    "RUH": "SA",
    "JED": "SA",
    "DMM": "SA",
    "MED": "SA",
    "KWI": "KW",
    "BOM": "IN",
    "DEL": "IN",
    "MAA": "IN",
    "BLR": "IN",
    "CCU": "IN",
    "SIN": "SG",
    "BKK": "TH",
    "KUL": "MY",
    "HKT": "TH",
    "MNL": "PH",
    "SGN": "VN",
    "HAN": "VN",
    "PEK": "CN",
    "PVG": "CN",
    "SZX": "CN",
}


def _extract_tax_airport_queries(
    airport_query: str | None = None, route_query: str | None = None
) -> list[str] | None:
    """Normalize explicit tax-airport input from `--airport` or legacy `--route`."""
    raw_query = (airport_query or "").strip() or (route_query or "").strip()
    if not raw_query:
        return None

    normalized_queries: list[str] = []
    for chunk in raw_query.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue

        if "-" in chunk:
            route_candidate = re.sub(r"\s+", "", chunk)
            try:
                origin, _destination = validate_route(route_candidate)
                normalized_queries.append(origin)
                continue
            except ValidationError:
                pass

        normalized_queries.append(chunk)

    return normalized_queries or None


def _tax_airport_display_name(
    airport_code: str, airport_info: dict, config: dict
) -> str:
    """Return the most user-friendly label for a configured tax airport."""
    city_name = str(config.get("city_names", {}).get(airport_code, "") or "").strip()
    if city_name:
        return city_name
    city = str(airport_info.get("city", "") or "").strip()
    if city:
        return city
    info_name = str(airport_info.get("name", "") or "").strip()
    if info_name:
        return info_name
    return airport_code


def _tax_airport_name_aliases(
    airport_code: str, airport_info: dict, config: dict
) -> list[str]:
    """Return configured non-code aliases that can identify a tax airport."""
    aliases: list[str] = []
    for alias in (
        config.get("city_names", {}).get(airport_code),
        airport_info.get("city"),
        airport_info.get("name"),
    ):
        text = str(alias or "").strip()
        if not text:
            continue
        if text.casefold() == airport_code.casefold():
            continue
        if any(text.casefold() == existing.casefold() for existing in aliases):
            continue
        aliases.append(text)
    return aliases


@lru_cache(maxsize=1)
def _load_global_airport_directory() -> dict[str, dict]:
    """Load a global IATA airport directory for explicit Future Tax searches."""
    if airportsdata is None:
        return {}

    searchable: dict[str, dict] = {}
    for airport_code, airport_info in airportsdata.load("IATA").items():
        normalized_code = str(airport_code or "").upper().strip()
        try:
            normalized_code = validate_airport_code(normalized_code)
        except ValidationError:
            continue

        country_code = str(airport_info.get("country", "") or "").upper().strip()
        if not country_code:
            continue

        entry = {
            "country": country_code,
            "_source": "global",
        }
        city_name = str(airport_info.get("city", "") or "").strip()
        if city_name:
            entry["city"] = city_name
        airport_name = str(airport_info.get("name", "") or "").strip()
        if airport_name:
            entry["name"] = airport_name

        searchable[normalized_code] = entry

    return searchable


def _configured_airport_country_codes(config: dict) -> dict[str, str]:
    """Return known airport -> country code mappings for explicit tax searches."""
    country_codes = dict(DEFAULT_AIRPORT_COUNTRY_CODES)
    for airport_code, country_code in config.get("airport_country_codes", {}).items():
        country_codes[str(airport_code).upper()] = str(country_code).upper()
    for airport_code, airport_info in config.get("tax_airports", {}).items():
        country_code = str(airport_info.get("country", "") or "").upper()
        if country_code:
            country_codes[str(airport_code).upper()] = country_code
    return country_codes


def _build_searchable_tax_airports(config: dict) -> dict[str, dict]:
    """Return airports that can be used for explicit Future Tax lookups."""
    searchable = {
        airport_code: dict(airport_info)
        for airport_code, airport_info in _load_global_airport_directory().items()
    }

    for airport_code, country_code in _configured_airport_country_codes(config).items():
        existing = dict(searchable.get(airport_code, {}))
        existing["country"] = country_code
        if not existing.get("_source"):
            existing["_source"] = "config"
        searchable[airport_code] = existing

    for airport_code, city_name in config.get("city_names", {}).items():
        normalized_code = str(airport_code).upper()
        if normalized_code not in searchable:
            continue
        text = str(city_name or "").strip()
        if text:
            searchable[normalized_code]["city"] = text

    for airport_code, airport_info in config.get("tax_airports", {}).items():
        existing = dict(searchable.get(airport_code, {}))
        existing.update(dict(airport_info))
        existing["_source"] = "config"
        searchable[airport_code] = existing

    return searchable


def _format_tax_airport_candidates(
    airport_codes: list[str], tax_airports: dict, config: dict, max_candidates: int = 12
) -> str:
    """Return a compact list of configured tax-airport choices."""
    labels = []
    shown_codes = airport_codes[:max_candidates]
    for airport_code in shown_codes:
        airport_info = tax_airports.get(airport_code, {})
        display_name = _tax_airport_display_name(airport_code, airport_info, config)
        extra_name = str(airport_info.get("name", "") or "").strip()
        if extra_name and extra_name.casefold() != display_name.casefold():
            labels.append(f"{airport_code} ({display_name} / {extra_name})")
        else:
            labels.append(f"{airport_code} ({display_name})")
    if len(airport_codes) > max_candidates:
        labels.append(f"... ({len(airport_codes) - max_candidates} more)")
    return ", ".join(labels)


def _has_global_tax_airport_search(tax_airports: dict) -> bool:
    """Return True when the explicit tax resolver includes the global airport directory."""
    return any(
        str(airport_info.get("_source", "")).casefold() == "global"
        for airport_info in tax_airports.values()
    )


def _resolve_tax_airport_query(
    query: str, tax_airports: dict, config: dict
) -> tuple[str, dict, str]:
    """Resolve a single airport code or configured airport name to one tax airport."""
    query_text = str(query or "").strip()
    if not query_text:
        raise ValidationError("airport", query, "cannot be empty")

    query_key = query_text.casefold()
    search_scope = (
        "airports"
        if _has_global_tax_airport_search(tax_airports)
        else "configured tax airports"
    )

    for airport_code, airport_info in tax_airports.items():
        if airport_code.casefold() == query_key:
            return airport_code, airport_info, airport_code

    exact_name_matches: list[tuple[str, str]] = []
    partial_matches: list[tuple[str, str]] = []

    for airport_code, airport_info in tax_airports.items():
        aliases = _tax_airport_name_aliases(airport_code, airport_info, config)
        exact_alias = next(
            (alias for alias in aliases if alias.casefold() == query_key),
            None,
        )
        if exact_alias:
            exact_name_matches.append((airport_code, exact_alias))
            continue

        partial_alias = next(
            (alias for alias in aliases if query_key in alias.casefold()),
            None,
        )
        if partial_alias:
            partial_matches.append((airport_code, partial_alias))

    if len(exact_name_matches) == 1:
        airport_code, matched_alias = exact_name_matches[0]
        return airport_code, tax_airports[airport_code], matched_alias

    if len(exact_name_matches) > 1:
        matched_codes = [airport_code for airport_code, _alias in exact_name_matches]
        raise ValidationError(
            "airport",
            query,
            f"matches multiple {search_scope}: "
            + _format_tax_airport_candidates(matched_codes, tax_airports, config),
        )

    if len(partial_matches) == 1:
        airport_code, matched_alias = partial_matches[0]
        return airport_code, tax_airports[airport_code], matched_alias

    if len(partial_matches) > 1:
        matched_codes = [airport_code for airport_code, _alias in partial_matches]
        raise ValidationError(
            "airport",
            query,
            f"matches multiple {search_scope}: "
            + _format_tax_airport_candidates(matched_codes, tax_airports, config),
        )

    if _has_global_tax_airport_search(tax_airports):
        raise ValidationError(
            "airport",
            query,
            "not found in known airports. Try a 3-letter airport code like SYD or a more specific airport or city name.",
        )

    raise ValidationError(
        "airport",
        query,
        "not found in configured tax airports. Valid options: "
        + _format_tax_airport_candidates(
            sorted(tax_airports.keys()), tax_airports, config
        ),
    )


def _configured_route_airports(commands_file: str) -> set[str]:
    """Return airport codes referenced by configured FD commands."""
    route_airports: set[str] = set()
    if not os.path.exists(commands_file):
        return route_airports

    with open(commands_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("FD") and "/" in line and len(line) >= 8:
                route_airports.add(line[2:5].upper())
                route_airports.add(line[5:8].upper())
    return route_airports


def _filter_tax_airports_by_configured_routes(
    tax_airports: dict, commands_file: str
) -> tuple[dict, int]:
    """Filter tax airports to those appearing in configured routes when possible."""
    route_airports = _configured_route_airports(commands_file)
    if not route_airports:
        return tax_airports, 0

    filtered = {
        airport_code: airport_info
        for airport_code, airport_info in tax_airports.items()
        if airport_code.upper() in route_airports
    }
    if not filtered:
        return tax_airports, 0

    return filtered, len(tax_airports) - len(filtered)
