import json
import shutil
from pathlib import Path
import pytest
from main import (
    _build_searchable_tax_airports,
    _build_explicit_route_commands,
    _command_matches_route,
    _extract_tax_airport_queries,
    _ensure_commands_template,
    _fd_output_has_fares,
    _fd_output_is_no_fares,
    _find_pure_airline_option_in_fs_page,
    _fs_output_is_no_results,
    _normalize_database_url,
    _parse_requested_routes,
    _resolve_tax_airport_query,
    _resolve_explicit_airline_codes,
    _should_use_tqdm,
    _resolve_database_url,
    _route_variants,
    _select_tax_airports_for_run,
    _should_recheck_same_fs_page,
    _should_run_fs_extraction,
    load_config,
)
from types import SimpleNamespace
from exceptions import ValidationError


def _make_local_temp_dir(name: str):
    path = Path.cwd() / name
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    return path


TEST_TAX_CONFIG = {
    "commands_file": "commands.txt",
    "rbd_sort_order": ["Y"],
    "airline_names": {"BG": "Biman Bangladesh"},
    "city_names": {
        "DAC": "Dhaka",
        "SIN": "Singapore",
        "KUL": "Kuala Lumpur",
        "MCT": "Muscat",
        "DXB": "Dubai",
        "AUH": "Abu Dhabi",
        "SHJ": "Sharjah",
    },
    "tax_airports": {
        "SIN": {"country": "SG", "name": "Singapore"},
        "KUL": {"country": "MY", "name": "Malaysia"},
        "MCT": {"country": "OM", "name": "Oman"},
        "DXB": {"country": "AE", "name": "UAE"},
        "AUH": {"country": "AE", "name": "UAE"},
        "SHJ": {"country": "AE", "name": "UAE"},
    },
    "airport_country_codes": {
        "DAC": "BD",
        "KUL": "MY",
        "MCT": "OM",
        "DXB": "AE",
        "AUH": "AE",
        "SHJ": "AE",
    },
}


def test_route_variants_include_reverse_by_default():
    assert _route_variants("DAC-MCT") == {"DACMCT", "MCTDAC"}


def test_route_variants_can_be_limited_to_one_direction():
    assert _route_variants("DAC-MCT", one_direction=True) == {"DACMCT"}


def test_command_matches_both_directions_by_default():
    forward = {"origin": "DAC", "destination": "MCT", "command": "FDACMCT/BG"}
    reverse = {"origin": "MCT", "destination": "DAC", "command": "FMCTDAC/BG"}

    assert _command_matches_route(forward, "DAC-MCT")
    assert _command_matches_route(reverse, "DAC-MCT")


def test_command_matches_only_exact_direction_when_requested():
    forward = {"origin": "DAC", "destination": "MCT", "command": "FDACMCT/BG"}
    reverse = {"origin": "MCT", "destination": "DAC", "command": "FMCTDAC/BG"}

    assert _command_matches_route(forward, "DAC-MCT", one_direction=True)
    assert not _command_matches_route(reverse, "DAC-MCT", one_direction=True)


def test_command_falls_back_to_raw_command_text_when_needed():
    reverse = {"command": "FMCTDAC/BG"}

    assert _command_matches_route(reverse, "DAC-MCT")
    assert not _command_matches_route(reverse, "DAC-MCT", one_direction=True)


def test_extract_tax_airport_queries_uses_first_airport_from_route_like_input():
    assert _extract_tax_airport_queries(route_query="KUL-DAC") == ["KUL"]


def test_extract_tax_airport_queries_accepts_comma_separated_values():
    assert _extract_tax_airport_queries(airport_query="KUL,MCT") == ["KUL", "MCT"]


def test_extract_tax_airport_queries_accepts_mixed_names_and_route_aliases():
    assert _extract_tax_airport_queries(
        airport_query="Kuala Lumpur, MCT-DAC, Muscat"
    ) == ["Kuala Lumpur", "MCT", "Muscat"]


def test_extract_tax_airport_queries_keeps_six_letter_city_name():
    assert _extract_tax_airport_queries(airport_query="Muscat") == ["Muscat"]


def test_parse_requested_routes_normalizes_and_deduplicates():
    assert _parse_requested_routes("dac-mct, DACMCT, cgp-doh") == [
        "DAC-MCT",
        "CGP-DOH",
    ]


def test_resolve_explicit_airline_codes_uses_filter_when_present():
    assert _resolve_explicit_airline_codes("bg, ek, BG", TEST_TAX_CONFIG) == [
        "BG",
        "EK",
    ]


def test_resolve_explicit_airline_codes_defaults_to_configured_airlines():
    assert _resolve_explicit_airline_codes(None, TEST_TAX_CONFIG) == ["BG"]


def test_build_explicit_route_commands_generates_both_directions_for_all_airlines():
    config = {
        **TEST_TAX_CONFIG,
        "airline_names": {"BG": "Biman Bangladesh", "BS": "US-Bangla"},
    }

    commands, routes, airlines = _build_explicit_route_commands(
        "DAC-MCT", None, config, one_direction=False
    )

    assert routes == ["DAC-MCT"]
    assert airlines == ["BG", "BS"]
    assert [command["command"] for command in commands] == [
        "FDDACMCT/BG",
        "FDDACMCT/BS",
        "FDMCTDAC/BG",
        "FDMCTDAC/BS",
    ]


def test_build_explicit_route_commands_honors_one_direction_and_airline_filter():
    commands, routes, airlines = _build_explicit_route_commands(
        "DAC-KWI", "KU", TEST_TAX_CONFIG, one_direction=True
    )

    assert routes == ["DAC-KWI"]
    assert airlines == ["KU"]
    assert [command["command"] for command in commands] == ["FDDACKWI/KU"]


def test_resolve_tax_airport_query_matches_exact_code():
    code, info, matched_alias = _resolve_tax_airport_query(
        "KUL", TEST_TAX_CONFIG["tax_airports"], TEST_TAX_CONFIG
    )

    assert code == "KUL"
    assert info["country"] == "MY"
    assert matched_alias == "KUL"


def test_resolve_tax_airport_query_matches_exact_city_name():
    code, _info, matched_alias = _resolve_tax_airport_query(
        "Kuala Lumpur", TEST_TAX_CONFIG["tax_airports"], TEST_TAX_CONFIG
    )

    assert code == "KUL"
    assert matched_alias == "Kuala Lumpur"


def test_resolve_tax_airport_query_matches_unique_partial_name():
    code, _info, matched_alias = _resolve_tax_airport_query(
        "muscat", TEST_TAX_CONFIG["tax_airports"], TEST_TAX_CONFIG
    )

    assert code == "MCT"
    assert matched_alias == "Muscat"


def test_resolve_tax_airport_query_rejects_ambiguous_country_name():
    with pytest.raises(ValidationError, match="matches multiple configured tax airports"):
        _resolve_tax_airport_query("uae", TEST_TAX_CONFIG["tax_airports"], TEST_TAX_CONFIG)


def test_resolve_tax_airport_query_matches_global_airport_code():
    searchable = _build_searchable_tax_airports(
        {"city_names": {}, "tax_airports": {}, "airport_country_codes": {}}
    )

    code, info, matched_alias = _resolve_tax_airport_query("SYD", searchable, TEST_TAX_CONFIG)

    assert code == "SYD"
    assert info["country"] == "AU"
    assert matched_alias == "SYD"


def test_resolve_tax_airport_query_matches_unique_global_airport_name():
    searchable = _build_searchable_tax_airports(
        {"city_names": {}, "tax_airports": {}, "airport_country_codes": {}}
    )

    code, info, matched_alias = _resolve_tax_airport_query(
        "Kingsford Smith", searchable, TEST_TAX_CONFIG
    )

    assert code == "SYD"
    assert info["country"] == "AU"
    assert matched_alias == "Sydney Kingsford Smith International Airport"


def test_resolve_tax_airport_query_rejects_ambiguous_global_city_name():
    searchable = _build_searchable_tax_airports(
        {"city_names": {}, "tax_airports": {}, "airport_country_codes": {}}
    )

    with pytest.raises(ValidationError, match="matches multiple airports"):
        _resolve_tax_airport_query("Sydney", searchable, TEST_TAX_CONFIG)


def test_route_like_tax_alias_fails_when_first_airport_is_not_configured():
    first_airport = _extract_tax_airport_queries(route_query="XXX-MCT")[0]

    with pytest.raises(ValidationError, match="not found"):
        _resolve_tax_airport_query(
            first_airport,
            {
                **TEST_TAX_CONFIG["tax_airports"],
                "DAC": {"country": "BD"},
                "KUL": {"country": "MY"},
            },
            TEST_TAX_CONFIG,
        )


def test_select_tax_airports_for_run_prefers_explicit_airport():
    args = SimpleNamespace(airport="KUL", route=None, limit=0)

    selected, metadata = _select_tax_airports_for_run(TEST_TAX_CONFIG, args)

    assert list(selected.keys()) == ["KUL"]
    assert metadata["resolved_codes"] == ["KUL"]
    assert metadata["resolutions"][0]["display_name"] == "Kuala Lumpur"


def test_select_tax_airports_for_run_allows_explicit_airport_outside_default_tax_list():
    args = SimpleNamespace(airport="DAC", route=None, limit=0)

    selected, metadata = _select_tax_airports_for_run(TEST_TAX_CONFIG, args)

    assert list(selected.keys()) == ["DAC"]
    assert selected["DAC"]["country"] == "BD"
    assert metadata["resolutions"][0]["display_name"] == "Dhaka"


def test_select_tax_airports_for_run_accepts_legacy_route_alias():
    args = SimpleNamespace(airport=None, route="DAC-MCT", limit=0)

    selected, metadata = _select_tax_airports_for_run(TEST_TAX_CONFIG, args)

    assert list(selected.keys()) == ["DAC"]
    assert metadata["requested_queries"] == ["DAC"]


def test_select_tax_airports_for_run_accepts_global_route_alias():
    args = SimpleNamespace(airport=None, route="SYD-DAC", limit=0)

    selected, metadata = _select_tax_airports_for_run(TEST_TAX_CONFIG, args)

    assert list(selected.keys()) == ["SYD"]
    assert selected["SYD"]["country"] == "AU"
    assert metadata["requested_queries"] == ["SYD"]


def test_select_tax_airports_for_run_accepts_multiple_explicit_airports():
    args = SimpleNamespace(airport="KUL,Muscat", route=None, limit=0)

    selected, metadata = _select_tax_airports_for_run(TEST_TAX_CONFIG, args)

    assert list(selected.keys()) == ["KUL", "MCT"]
    assert metadata["requested_queries"] == ["KUL", "Muscat"]
    assert metadata["resolved_codes"] == ["KUL", "MCT"]


def test_select_tax_airports_for_run_deduplicates_same_airport():
    args = SimpleNamespace(airport="KUL,Kuala Lumpur", route=None, limit=0)

    selected, metadata = _select_tax_airports_for_run(TEST_TAX_CONFIG, args)

    assert list(selected.keys()) == ["KUL"]
    assert metadata["resolved_codes"] == ["KUL"]
    assert len(metadata["resolutions"]) == 1


def test_select_tax_airports_for_run_allows_global_airport_without_configured_defaults():
    config = {
        **TEST_TAX_CONFIG,
        "city_names": {},
        "tax_airports": {},
        "airport_country_codes": {},
    }
    args = SimpleNamespace(airport="SYD", route=None, limit=0)

    selected, metadata = _select_tax_airports_for_run(config, args)

    assert list(selected.keys()) == ["SYD"]
    assert selected["SYD"]["country"] == "AU"
    assert metadata["resolved_codes"] == ["SYD"]


def test_select_tax_airports_for_run_uses_configured_routes_when_no_explicit_query(
    monkeypatch,
):
    tmp_path = _make_local_temp_dir("tmp_test_tax_airport_selection")
    commands_path = tmp_path / "commands.txt"
    commands_path.write_text(
        "\n".join(
            [
                "FDDACKUL/BG",
                "FDKULDAC/BG",
                "FDDACMCT/BG",
                "FDMCTDAC/BG",
            ]
        ),
        encoding="utf-8",
    )

    args = SimpleNamespace(airport=None, route=None, limit=0)

    try:
        import main

        monkeypatch.setattr(main, "SCRIPT_DIR", str(tmp_path))
        selected, metadata = _select_tax_airports_for_run(TEST_TAX_CONFIG, args)

        assert list(selected.keys()) == ["KUL", "MCT"]
        assert metadata["requested_queries"] == []
        assert metadata["skipped_by_route_filter"] == 4
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_database_url_prefers_environment(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg2://postgres:secret@localhost:5432/GDS_Automation",
    )

    resolved = _resolve_database_url(
        {"database_url": "postgresql://user:password@localhost/GDS_Automation"}
    )

    assert resolved.startswith("postgresql://postgres:secret@localhost:5432/")
    assert "connect_timeout=5" in resolved


def test_database_url_ignores_placeholder_config(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert (
        _resolve_database_url(
            {"database_url": "postgresql://user:password@localhost/GDS_Automation"}
        )
        == ""
    )


def test_database_url_normalizes_sqlalchemy_prefix():
    normalized = _normalize_database_url(
        "postgresql+psycopg2://postgres:secret@localhost:5432/GDS_Automation"
    )

    assert normalized.startswith(
        "postgresql://postgres:secret@localhost:5432/GDS_Automation"
    )
    assert "connect_timeout=5" in normalized


def test_fd_output_has_fares_requires_actual_fare_rows():
    assert _fd_output_has_fares("") is False
    assert _fd_output_has_fares("NO FARES FOUND") is False
    assert _fd_output_has_fares("DACMCT\n  1  BG  100.00   YOW      Y\nEND") is True


def test_fd_output_is_no_fares_matches_smartpoint_terminal_message():
    assert _fd_output_is_no_fares("NO FARES FOUND FOR INPUT REQUEST") is True
    assert _fd_output_is_no_fares("NO FARES FOUND") is False
    assert _fd_output_is_no_fares("DACMCT\n  1  BG  100.00   YOW      Y\nEND") is False


def test_fs_output_is_no_results_matches_terminal_errors():
    assert _fs_output_is_no_results("NO FARES FOUND FOR INPUT REQUEST") is True
    assert _fs_output_is_no_results("CHECK ACTION CODE") is True
    assert _fs_output_is_no_results("INVALID") is True
    assert _fs_output_is_no_results("PRICING OPTION 1\n1   BG  721  H") is False


def test_should_run_fs_extraction_skips_when_fd_has_no_fares():
    args = SimpleNamespace(only_fd=False, only_yq=False, only_currency=False)

    assert _should_run_fs_extraction(args, "") is False
    assert _should_run_fs_extraction(args, "NO FARES FOUND") is False


def test_should_run_fs_extraction_allows_explicit_tax_only_modes():
    only_yq_args = SimpleNamespace(only_fd=False, only_yq=True, only_currency=False)
    only_currency_args = SimpleNamespace(
        only_fd=False, only_yq=False, only_currency=True
    )

    assert _should_run_fs_extraction(only_yq_args, "") is True
    assert _should_run_fs_extraction(only_currency_args, "") is True


def test_find_pure_airline_option_in_fs_page_finds_direct_match():
    fs_text = """
PRICING OPTION 1
1   WY    318  L  15APR DAC MCT

PRICING OPTION 2
1   BG    340  Y  16MAY RUH DAC
"""

    option_index, option_number, option_count = _find_pure_airline_option_in_fs_page(
        fs_text, "BG"
    )

    assert option_index == 1
    assert option_number == "2"
    assert option_count == 2


def test_find_pure_airline_option_in_fs_page_handles_prefixed_airline_codes():
    fs_text = """
PRICING OPTION 1
1  #FZ    524  N  16APR DXB DAC

PRICING OPTION 2
1   BG    340  Y  16MAY RUH DAC
"""

    option_index, option_number, option_count = _find_pure_airline_option_in_fs_page(
        fs_text, "FZ"
    )

    assert option_index == 0
    assert option_number == "1"
    assert option_count == 2


def test_pure_finder_returns_option_2_on_mixed_page():
    # Option 1 has BG outbound + WY return (mixed); option 2 is pure BG.
    # Pure finder must skip option 1 and return option 2.
    mixed_page = """
PRICING OPTION 1
 1   BG   BG 421  Y 02JUN  ZYL  DAC 1155 1240
 2   WY   WY 182  Y 02JUN  DAC  MCT 1540 1800

PRICING OPTION 2
 1   BG   BG 501  Y 02JUN  ZYL  DAC 1000 1045
 2   BG   BG 301  Y 02JUN  DAC  MCT 1300 1530

"""
    idx, num, count = _find_pure_airline_option_in_fs_page(mixed_page, "BG")
    assert idx == 1
    assert num == "2"
    assert count == 2


def test_should_recheck_same_fs_page_when_refreshed_page_adds_target_option():
    current_page = """
PRICING OPTION 1
1   EK    816  U  16MAY RUH DXB
"""
    refreshed_page = """
PRICING OPTION 1
1   BG    340  Y  16MAY RUH DAC
"""

    assert _should_recheck_same_fs_page(current_page, refreshed_page, "BG") is True


def test_should_recheck_same_fs_page_ignores_unchanged_text():
    current_page = """
PRICING OPTION 1
1   BG    340  Y  16MAY RUH DAC
"""

    assert _should_recheck_same_fs_page(current_page, current_page, "BG") is False


def test_ensure_commands_template_creates_starter_file():
    tmp_path = _make_local_temp_dir("tmp_test_commands_template")
    commands_path = tmp_path / "commands.txt"

    try:
        created = _ensure_commands_template(str(commands_path))

        assert created is True
        assert commands_path.exists()
        assert "FDDACMCT/BG" in commands_path.read_text(encoding="utf-8")
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_load_config_seeds_default_config_from_bundle(monkeypatch):
    tmp_path = _make_local_temp_dir("tmp_test_bundled_config")
    runtime_config = tmp_path / "config.json"
    bundled_config = tmp_path / "bundled_config.json"
    try:
        bundled_config.write_text(
            json.dumps(
                {
                    "commands_file": "commands.txt",
                    "rbd_sort_order": ["Y"],
                    "airline_names": {"BG": "Biman Bangladesh"},
                    "city_names": {"DAC": "Dhaka"},
                    "tax_airports": {},
                }
            ),
            encoding="utf-8",
        )

        import main

        monkeypatch.setattr(main, "DEFAULT_CONFIG", str(runtime_config))
        monkeypatch.setattr(
            main, "_resolve_bundled_file", lambda filename: str(bundled_config)
        )
        # Disable remote fetch so the test exercises the local bundle-seed path
        monkeypatch.setattr(main, "_fetch_remote_config", lambda: None)

        config = load_config(str(runtime_config))

        assert runtime_config.exists()
        assert config["airline_names"]["BG"] == "Biman Bangladesh"
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_should_use_tqdm_is_disabled_for_gui_mode():
    assert _should_use_tqdm(gui_mode=True) is False
