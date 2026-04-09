from main import (
    _command_matches_route,
    _normalize_database_url,
    _resolve_database_url,
    _route_variants,
)


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
