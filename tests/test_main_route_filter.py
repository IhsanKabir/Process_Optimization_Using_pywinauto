import json
import shutil
from pathlib import Path
from main import (
    _command_matches_route,
    _ensure_commands_template,
    _fd_output_has_fares,
    _find_pure_airline_option_in_fs_page,
    _normalize_database_url,
    _should_use_tqdm,
    _resolve_database_url,
    _route_variants,
    _should_recheck_same_fs_page,
    _should_run_fs_extraction,
    load_config,
)
from types import SimpleNamespace


def _make_local_temp_dir(name: str):
    path = Path.cwd() / name
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    return path


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
