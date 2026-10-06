"""fs_screens.py - Predicates over raw FD/FS terminal screens."""

import re

from parser import parse_fare_display

FS_OPTION_PATTERN = re.compile(
    r"PRICING\s+OPTION\s+(\d+)(.*?(?=PRICING\s+OPTION\s+\d+|$))",
    re.IGNORECASE | re.DOTALL,
)

FS_LEG_PATTERN = re.compile(r"^\s*(\d+)\s+[#@-]?([A-Z0-9]{2})\s+", re.MULTILINE)


def _fd_output_has_fares(raw_text: str) -> bool:
    """Return True when FD output contains actual fare rows."""
    if not raw_text or not raw_text.strip():
        return False
    parsed = parse_fare_display(raw_text)
    return bool(parsed.get("fares"))


def _fd_output_is_no_fares(raw_text: str) -> bool:
    """Return True when Smartpoint definitively says the FD request has no fares."""
    upper = (raw_text or "").upper()
    return "NO FARES FOUND" in upper and "INPUT REQUEST" in upper


def _fs_output_is_no_results(raw_text: str) -> bool:
    """Return True when FS checkout has returned a final no-result/error screen."""
    upper = (raw_text or "").upper()
    return any(
        marker in upper
        for marker in (
            "NO FARES FOUND",
            "CHECK ACTION CODE",
            "INVALID",
        )
    )


def _should_run_fs_extraction(args, fd_terminal_text: str) -> bool:
    """Skip FS when normal FD extraction produced no fare rows."""
    if getattr(args, "only_fd", False):
        return False
    if getattr(args, "only_yq", False) or getattr(args, "only_currency", False):
        return True
    return _fd_output_has_fares(fd_terminal_text)


def _find_pure_airline_option_in_fs_page(
    fs_text: str, airline: str
) -> tuple[int | None, str | None, int]:
    """Find the first pricing option on the current FS page containing only the target airline."""
    options = list(FS_OPTION_PATTERN.finditer(fs_text or ""))
    airline_upper = (airline or "").upper()

    for option_index, opt_match in enumerate(options):
        opt_num = opt_match.group(1)
        block = opt_match.group(2)
        leg_matches = FS_LEG_PATTERN.findall(block)
        if not leg_matches:
            continue

        leg_airlines = [match[1].upper().strip() for match in leg_matches]
        if all(code == airline_upper for code in leg_airlines):
            return option_index, opt_num, len(options)

    return None, None, len(options)


def _should_recheck_same_fs_page(
    current_fs_page: str, refreshed_fs_page: str, airline: str
) -> bool:
    """Return True when a same-date FS page looks more complete after settling."""
    current_text = (current_fs_page or "").strip()
    refreshed_text = (refreshed_fs_page or "").strip()
    if not refreshed_text or refreshed_text == current_text:
        return False

    (
        current_option_index,
        _current_option_number,
        current_option_count,
    ) = _find_pure_airline_option_in_fs_page(current_text, airline)
    (
        refreshed_option_index,
        _refreshed_option_number,
        refreshed_option_count,
    ) = _find_pure_airline_option_in_fs_page(refreshed_text, airline)

    if refreshed_option_index is not None and current_option_index is None:
        return True

    if refreshed_option_count > current_option_count:
        return True

    return (
        "PRICING OPTION" in refreshed_text.upper()
        and len(refreshed_text) > len(current_text) + 40
    )
