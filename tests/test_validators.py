"""
Unit tests for validators.py

Tests input validation functions.
"""

from copy import deepcopy

import pytest
from validators import (
    validate_airport_code,
    validate_airline_code,
    validate_route,
    validate_country_code,
    validate_config,
    sanitize_command,
    validate_limit,
)
from exceptions import ValidationError, ConfigurationError
from tests.fixtures.sample_data import SAMPLE_CONFIG


class TestValidateAirportCode:
    """Test airport code validation."""

    def test_valid_airport_codes(self):
        """Test valid 3-letter airport codes."""
        assert validate_airport_code("DAC") == "DAC"
        assert validate_airport_code("mle") == "MLE"
        assert validate_airport_code(" cgp ") == "CGP"

    def test_invalid_airport_codes(self):
        """Test invalid airport codes raise ValidationError."""
        with pytest.raises(ValidationError):
            validate_airport_code("")

        with pytest.raises(ValidationError):
            validate_airport_code("DA")  # Too short

        with pytest.raises(ValidationError):
            validate_airport_code("DACX")  # Too long

        with pytest.raises(ValidationError):
            validate_airport_code("D1C")  # Contains number

        with pytest.raises(ValidationError):
            validate_airport_code("DA-C")  # Contains special char


class TestValidateAirlineCode:
    """Test airline code validation."""

    def test_valid_airline_codes(self):
        """Test valid 2-character airline codes."""
        assert validate_airline_code("BG") == "BG"
        assert validate_airline_code("bs") == "BS"
        assert validate_airline_code("8D") == "8D"  # Numeric allowed

    def test_invalid_airline_codes(self):
        """Test invalid airline codes."""
        with pytest.raises(ValidationError):
            validate_airline_code("")

        with pytest.raises(ValidationError):
            validate_airline_code("B")  # Too short

        with pytest.raises(ValidationError):
            validate_airline_code("BGX")  # Too long

        with pytest.raises(ValidationError):
            validate_airline_code("B-")  # Special char


class TestValidateRoute:
    """Test route validation."""

    def test_valid_routes(self):
        """Test valid route strings."""
        origin, dest = validate_route("DAC-MLE")
        assert origin == "DAC"
        assert dest == "MLE"

        origin, dest = validate_route("DACMLE")  # No dash
        assert origin == "DAC"
        assert dest == "MLE"

        origin, dest = validate_route("dac-cgp")  # Lowercase
        assert origin == "DAC"
        assert dest == "CGP"

    def test_invalid_routes(self):
        """Test invalid routes."""
        with pytest.raises(ValidationError):
            validate_route("")

        with pytest.raises(ValidationError):
            validate_route("DACML")  # Too short

        with pytest.raises(ValidationError):
            validate_route("DACMLEX")  # Too long

        with pytest.raises(ValidationError):
            validate_route("DACDAC")  # Same origin/dest


class TestValidateCountryCode:
    """Test country code validation."""

    def test_valid_country_codes(self):
        """Test valid 2-letter country codes."""
        assert validate_country_code("SG") == "SG"
        assert validate_country_code("mv") == "MV"

    def test_invalid_country_codes(self):
        """Test invalid country codes."""
        with pytest.raises(ValidationError):
            validate_country_code("")

        with pytest.raises(ValidationError):
            validate_country_code("S")  # Too short

        with pytest.raises(ValidationError):
            validate_country_code("SGP")  # Too long


class TestValidateConfig:
    """Test configuration validation."""

    def test_valid_config(self):
        """Test valid configuration passes validation."""
        config = deepcopy(SAMPLE_CONFIG)
        result = validate_config(config)
        assert result is not None
        assert "domestic_airports" in result

    def test_missing_required_keys(self):
        """Test missing required keys raises error."""
        config = {"commands_file": "test.txt"}  # Missing other required keys

        with pytest.raises(ConfigurationError, match="Missing required config keys"):
            validate_config(config)

    def test_invalid_airline_code_in_config(self):
        """Test invalid airline code in config."""
        config = deepcopy(SAMPLE_CONFIG)
        config["airline_names"]["TOOLONG"] = "Invalid Airline"

        with pytest.raises(ConfigurationError, match="Invalid airline code"):
            validate_config(config)

    def test_invalid_airport_code_in_config(self):
        """Test invalid airport code in config."""
        config = deepcopy(SAMPLE_CONFIG)
        config["city_names"]["DACC"] = "Invalid City"

        with pytest.raises(ConfigurationError, match="Invalid airport code"):
            validate_config(config)

    def test_adds_default_domestic_airports(self):
        """Test default domestic airports are added if missing."""
        config = deepcopy(SAMPLE_CONFIG)
        del config["domestic_airports"]

        result = validate_config(config)
        assert result["domestic_airports"] == ["DAC"]

    def test_invalid_tax_airports(self):
        """Test invalid tax airport configuration."""
        config = deepcopy(SAMPLE_CONFIG)
        config["tax_airports"]["INVALID"] = {"country": "SG"}

        with pytest.raises(ConfigurationError, match="Invalid airport code"):
            validate_config(config)


class TestSanitizeCommand:
    """Test command sanitization."""

    def test_valid_commands(self):
        """Test valid commands pass through."""
        assert sanitize_command("FDDACMLE/BG") == "FDDACMLE/BG"
        assert sanitize_command("  FTAX-SG  ") == "FTAX-SG"

    def test_dangerous_characters(self):
        """Test dangerous characters are rejected."""
        with pytest.raises(ValidationError, match="prohibited character"):
            sanitize_command("FDDACMLE;rm -rf")

        with pytest.raises(ValidationError):
            sanitize_command("FDDACMLE|cat")

        with pytest.raises(ValidationError):
            sanitize_command("FDDACMLE&whoami")

        with pytest.raises(ValidationError):
            sanitize_command("FDDACMLE\nINVALID")

    def test_length_limit(self):
        """Test command length limit."""
        long_command = "FD" + "X" * 200

        with pytest.raises(ValidationError, match="exceeds maximum length"):
            sanitize_command(long_command)


class TestValidateLimit:
    """Test limit validation."""

    def test_valid_limits(self):
        """Test valid limit values."""
        assert validate_limit(0) == 0
        assert validate_limit(10) == 10
        assert validate_limit(1000) == 1000

    def test_negative_limit(self):
        """Test negative limit is rejected."""
        with pytest.raises(ValidationError, match="cannot be negative"):
            validate_limit(-1)

    def test_excessive_limit(self):
        """Test excessively large limit is rejected."""
        with pytest.raises(ValidationError, match="exceeds maximum"):
            validate_limit(100000)
