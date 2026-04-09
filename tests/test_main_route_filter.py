from main import _command_matches_route, _route_variants


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
