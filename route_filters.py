"""route_filters.py - Route/airline filters for --route and --airline."""

from exceptions import ConfigurationError, ValidationError
from validators import validate_airline_code, validate_route


def _route_variants(route_code: str, one_direction: bool = False) -> set[str]:
    """Return the route directions that should be treated as a match."""
    normalized = (route_code or "").strip().upper().replace("-", "")
    if len(normalized) != 6:
        return set()
    if one_direction:
        return {normalized}
    return {normalized, f"{normalized[3:]}{normalized[:3]}"}


def _command_matches_route(
    command_entry: dict, route_code: str, one_direction: bool = False
) -> bool:
    """Check whether a command matches a route filter."""
    route_variants = _route_variants(route_code, one_direction=one_direction)
    if not route_variants:
        return False

    origin = str(command_entry.get("origin") or "").upper()
    destination = str(command_entry.get("destination") or "").upper()
    if origin and destination:
        return f"{origin}{destination}" in route_variants

    raw_command = str(command_entry.get("command") or "").upper().replace("-", "")
    return any(route_variant in raw_command for route_variant in route_variants)


def _parse_requested_routes(route_query: str | None) -> list[str]:
    """Normalize comma-separated route input into canonical `AAA-BBB` strings."""
    if not route_query:
        return []

    normalized_routes: list[str] = []
    seen_routes: set[str] = set()
    for raw_route in str(route_query).split(","):
        raw_route = raw_route.strip()
        if not raw_route:
            continue
        origin, destination = validate_route(raw_route)
        route_code = f"{origin}-{destination}"
        if route_code in seen_routes:
            continue
        seen_routes.add(route_code)
        normalized_routes.append(route_code)
    return normalized_routes


def _resolve_explicit_airline_codes(
    airline_query: str | None, config: dict
) -> list[str]:
    """Resolve explicit fare/penalty airline filters or fall back to configured airlines."""
    if airline_query:
        airline_codes: list[str] = []
        seen_codes: set[str] = set()
        for raw_code in str(airline_query).split(","):
            raw_code = raw_code.strip()
            if not raw_code:
                continue
            code = validate_airline_code(raw_code)
            if code in seen_codes:
                continue
            seen_codes.add(code)
            airline_codes.append(code)
        if airline_codes:
            return airline_codes

    airline_names = config.get("airline_names", {})
    if isinstance(airline_names, dict) and airline_names:
        return [str(code).upper() for code in airline_names.keys()]

    raise ConfigurationError(
        "No airlines available to generate explicit route commands. Add airline_names or provide --airline."
    )


def parse_route_pairs(text: str | None) -> list[tuple[str, str, str]]:
    """Parse "BS:DAC-BKK,FZ:DXB-DAC" into [(airline, origin, dest), ...].

    Used to re-run exact airline+route pairs (the report's Re-run Needed
    list) instead of every route x every airline.
    """
    pairs: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for raw in str(text or "").split(","):
        raw = raw.strip()
        if not raw:
            continue
        airline_part, sep, route_part = raw.partition(":")
        if not sep:
            raise ValidationError(
                "pairs", raw, "expected AIRLINE:ORIGIN-DEST, e.g. BS:DAC-BKK"
            )
        airline = validate_airline_code(airline_part.strip())
        origin, dest = validate_route(route_part.strip())
        pair = (airline, origin, dest)
        if pair not in seen:
            seen.add(pair)
            pairs.append(pair)
    return pairs


def select_pair_commands(
    commands: list[dict], pairs: list[tuple[str, str, str]]
) -> list[dict]:
    """Configured commands matching each exact pair, in pair order; a pair
    missing from commands.txt gets a generated FD command."""
    by_key = {
        (
            str(c.get("airline") or "").upper(),
            str(c.get("origin") or "").upper(),
            str(c.get("destination") or "").upper(),
        ): c
        for c in commands
    }
    selected: list[dict] = []
    for airline, origin, dest in pairs:
        selected.append(
            by_key.get(
                (airline, origin, dest),
                {
                    "origin": origin,
                    "destination": dest,
                    "airline": airline,
                    "route": f"{origin}-{dest}",
                    "command": f"FD{origin}{dest}/{airline}",
                },
            )
        )
    return selected


def _build_explicit_route_commands(
    route_query: str,
    airline_query: str | None,
    config: dict,
    one_direction: bool = False,
) -> tuple[list[dict], list[str], list[str]]:
    """Build FD commands directly from typed routes and airlines."""
    routes = _parse_requested_routes(route_query)
    if not routes:
        return [], [], []

    airline_codes = _resolve_explicit_airline_codes(airline_query, config)
    commands: list[dict] = []
    seen_commands: set[str] = set()

    for route_code in routes:
        origin, destination = route_code.split("-", 1)
        direction_pairs = [(origin, destination)]
        if not one_direction:
            direction_pairs.append((destination, origin))

        for dir_origin, dir_destination in direction_pairs:
            for airline_code in airline_codes:
                command = f"FD{dir_origin}{dir_destination}/{airline_code}"
                if command in seen_commands:
                    continue
                seen_commands.add(command)
                commands.append(
                    {
                        "origin": dir_origin,
                        "destination": dir_destination,
                        "airline": airline_code,
                        "route": f"{dir_origin}-{dir_destination}",
                        "command": command,
                    }
                )

    return commands, routes, airline_codes
