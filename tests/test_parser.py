"""
Unit tests for parser.py

Tests the fare display parsing logic with various input formats.
"""

import pytest
from parser import (
    parse_fare_display,
    group_fares_by_rbd,
    parse_command,
    generate_file_key
)
from tests.fixtures.sample_data import SAMPLE_FD_OUTPUT


class TestParseCommand:
    """Test command string parsing."""

    def test_parse_valid_command(self):
        """Test parsing a valid FD command."""
        result = parse_command("FDDACMLE/BG")
        assert result is not None
        assert result['origin'] == 'DAC'
        assert result['destination'] == 'MLE'
        assert result['airline'] == 'BG'
        assert result['route'] == 'DAC-MLE'

    def test_parse_lowercase_command(self):
        """Test parsing handles lowercase input."""
        result = parse_command("fddaccgp/bg")
        assert result is not None
        assert result['origin'] == 'DAC'
        assert result['airline'] == 'BG'

    def test_parse_invalid_command(self):
        """Test parsing returns None for invalid command."""
        assert parse_command("INVALID") is None
        assert parse_command("FDDAC/BG") is None  # Too short
        assert parse_command("FDDACMLEXX/BG") is None  # Too long


class TestParseFareDisplay:
    """Test fare display output parsing."""

    def test_parse_sample_output(self):
        """Test parsing sample FD output."""
        result = parse_fare_display(SAMPLE_FD_OUTPUT)

        assert 'fares' in result
        assert 'currency' in result
        assert result['currency'] == 'USD'
        assert len(result['fares']) == 4

    def test_parse_extracts_correct_fares(self):
        """Test that fares are extracted with correct values."""
        result = parse_fare_display(SAMPLE_FD_OUTPUT)
        fares = result['fares']

        # Check first fare
        assert fares[0]['line'] == 1
        assert fares[0]['airline'] == 'BG'
        assert fares[0]['fare'] == 100.00
        assert fares[0]['rbd'] == 'Y'
        assert fares[0]['fare_basis'] == 'YOW'
        assert fares[0]['is_rt'] is False

        # Check round-trip fare
        assert fares[1]['fare'] == 200.00
        assert fares[1]['is_rt'] is True
        assert fares[1]['fare_basis'] == 'JRT'

    def test_parse_empty_input(self):
        """Test parsing empty input returns empty result."""
        result = parse_fare_display("")
        assert result['fares'] == []
        assert result['currency'] is None

    def test_parse_no_currency(self):
        """Test parsing without currency header."""
        sample = """DACCGP
  1  BG  100.00   YOW      Y
END"""
        result = parse_fare_display(sample)
        assert result['currency'] is None
        assert len(result['fares']) == 1


class TestGroupFaresByRBD:
    """Test fare grouping by RBD."""

    def test_group_basic_fares(self):
        """Test basic fare grouping."""
        fares = [
            {'rbd': 'Y', 'fare': 100, 'is_rt': False, 'fare_basis': 'YOW', 'is_unsaleable': False},
            {'rbd': 'Y', 'fare': 200, 'is_rt': True, 'fare_basis': 'YRT', 'is_unsaleable': False},
            {'rbd': 'J', 'fare': 300, 'is_rt': False, 'fare_basis': 'JOW', 'is_unsaleable': False},
        ]

        grouped = group_fares_by_rbd(fares)

        assert 'Y' in grouped
        assert 'J' in grouped
        assert grouped['Y']['ow_fare'] == 100
        assert grouped['Y']['rt_fare'] == 200
        assert grouped['J']['ow_fare'] == 300
        assert grouped['J']['rt_fare'] is None

    def test_group_picks_lowest_fare(self):
        """Test that grouping picks the lowest fare for each RBD."""
        fares = [
            {'rbd': 'Y', 'fare': 150, 'is_rt': False, 'fare_basis': 'YOW1', 'is_unsaleable': False},
            {'rbd': 'Y', 'fare': 100, 'is_rt': False, 'fare_basis': 'YOW2', 'is_unsaleable': False},
            {'rbd': 'Y', 'fare': 120, 'is_rt': False, 'fare_basis': 'YOW3', 'is_unsaleable': False},
        ]

        grouped = group_fares_by_rbd(fares)

        assert grouped['Y']['ow_fare'] == 100
        assert grouped['Y']['ow_fare_basis'] == 'YOW2'

    def test_group_respects_sort_order(self):
        """Test that RBDs are sorted according to provided order."""
        fares = [
            {'rbd': 'Y', 'fare': 100, 'is_rt': False, 'fare_basis': 'YOW', 'is_unsaleable': False},
            {'rbd': 'J', 'fare': 300, 'is_rt': False, 'fare_basis': 'JOW', 'is_unsaleable': False},
            {'rbd': 'F', 'fare': 500, 'is_rt': False, 'fare_basis': 'FOW', 'is_unsaleable': False},
        ]

        sort_order = ['F', 'J', 'Y']
        grouped = group_fares_by_rbd(fares, sort_order)

        keys = list(grouped.keys())
        assert keys == ['F', 'J', 'Y']

    def test_group_marks_unsaleable(self):
        """Test that unsaleable fares are marked in basis code."""
        fares = [
            {'rbd': 'Y', 'fare': 100, 'is_rt': False, 'fare_basis': 'YOW', 'is_unsaleable': True},
        ]

        grouped = group_fares_by_rbd(fares)

        assert 'Y (Unsaleable)' in grouped
        assert '(Unsaleable)' in grouped['Y (Unsaleable)']['ow_fare_basis']


class TestGenerateFileKey:
    """Test file key generation."""

    def test_generate_file_key(self):
        """Test file key generation from command info."""
        command_info = {
            'airline': 'BG',
            'route': 'DAC-MLE',
            'origin': 'DAC',
            'destination': 'MLE'
        }

        key = generate_file_key(command_info)
        assert key == 'BG_DAC-MLE'
