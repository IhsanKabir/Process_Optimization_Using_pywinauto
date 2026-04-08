"""
test_validation_features.py - Tests for Data Validation Features

Tests the new validation functions added for fare amounts, currency codes,
and general data sanity checks.
"""

import pytest
from validators import (
    validate_fare_amount,
    validate_currency_code,
    validate_fare_data,
    validate_parsed_fares,
    VALID_CURRENCY_CODES,
)
from exceptions import ValidationError


class TestFareAmountValidation:
    """Tests for fare amount validation."""

    def test_valid_fare_amounts(self):
        """Test that valid fare amounts pass validation."""
        assert validate_fare_amount(100.0, "USD", warn_only=False) is True
        assert validate_fare_amount(1500.50, "BDT", warn_only=False) is True
        assert validate_fare_amount(0.01, "USD", warn_only=False) is True

    def test_negative_fare_raises_error(self):
        """Test that negative fares raise ValidationError."""
        with pytest.raises(ValidationError):
            validate_fare_amount(-100.0, "USD", warn_only=False)

    def test_zero_fare_raises_error(self):
        """Test that zero fares raise ValidationError."""
        with pytest.raises(ValidationError):
            validate_fare_amount(0.0, "USD", warn_only=False)

    def test_excessive_fare_raises_error(self):
        """Test that excessively high fares raise ValidationError."""
        with pytest.raises(ValidationError):
            validate_fare_amount(100000.0, "USD", warn_only=False)

    def test_warn_only_mode_returns_false(self):
        """Test that warn_only mode returns False instead of raising."""
        assert validate_fare_amount(-100.0, "USD", warn_only=True) is False
        assert validate_fare_amount(0.0, "USD", warn_only=True) is False
        assert validate_fare_amount(100000.0, "USD", warn_only=True) is False


class TestCurrencyCodeValidation:
    """Tests for currency code validation."""

    def test_valid_currency_codes(self):
        """Test that valid currency codes pass validation."""
        assert validate_currency_code("USD", warn_only=False) is True
        assert validate_currency_code("EUR", warn_only=False) is True
        assert validate_currency_code("BDT", warn_only=False) is True
        assert validate_currency_code("JPY", warn_only=False) is True

    def test_empty_currency_code(self):
        """Test that empty currency code is handled."""
        assert validate_currency_code(None, warn_only=True) is False
        assert validate_currency_code("", warn_only=True) is False

    def test_empty_currency_code_raises_error(self):
        """Test that empty currency code raises error when warn_only=False."""
        with pytest.raises(ValidationError):
            validate_currency_code(None, warn_only=False)

    def test_invalid_format_currency_code(self):
        """Test that invalid format currency codes are rejected."""
        assert validate_currency_code("US", warn_only=True) is False
        assert validate_currency_code("USDD", warn_only=True) is False
        assert validate_currency_code("12D", warn_only=True) is False

    def test_case_insensitive_validation(self):
        """Test that currency validation is case-insensitive."""
        assert validate_currency_code("usd", warn_only=False) is True
        assert validate_currency_code("Eur", warn_only=False) is True

    def test_uncommon_but_valid_currency(self):
        """Test uncommon but potentially valid currency codes."""
        # Should not raise error, and still returns True (valid format)
        result = validate_currency_code("XXX", warn_only=True)
        # XXX has valid format but is not in our common list
        # It returns True because the format is valid
        assert result is True


class TestFareDataValidation:
    """Tests for fare data dictionary validation."""

    def test_valid_fare_data(self):
        """Test that valid fare data passes validation."""
        fare_data = {
            "rbd": "Y",
            "airline": "BG",
            "fare_basis": "YOWUS",
            "ow_fare": 100.0,
            "rt_fare": 180.0,
        }
        warnings = validate_fare_data(fare_data, "USD", warn_only=True)
        assert warnings == []

    def test_missing_required_fields(self):
        """Test that missing required fields generate warnings."""
        fare_data = {"ow_fare": 100.0}
        warnings = validate_fare_data(fare_data, "USD", warn_only=True)
        assert len(warnings) > 0
        assert any("rbd" in w.lower() for w in warnings)
        assert any("airline" in w.lower() for w in warnings)

    def test_invalid_fare_amounts_in_data(self):
        """Test that invalid fare amounts generate warnings."""
        fare_data = {
            "rbd": "Y",
            "airline": "BG",
            "fare_basis": "YOWUS",
            "ow_fare": -100.0,  # Invalid
            "rt_fare": 0.0,  # Invalid
        }
        warnings = validate_fare_data(fare_data, "USD", warn_only=True)
        assert len(warnings) > 0

    def test_unsaleable_rbd_format(self):
        """Test that unsaleable RBD format is accepted."""
        fare_data = {
            "rbd": "Y (Unsaleable)",
            "airline": "BG",
            "fare_basis": "YOWUS",
            "ow_fare": 100.0,
        }
        warnings = validate_fare_data(fare_data, "USD", warn_only=True)
        # Should not generate RBD format warning
        assert not any("rbd" in w.lower() and "format" in w.lower() for w in warnings)


class TestParsedFaresValidation:
    """Tests for parsed fares list validation."""

    def test_validate_empty_fares_list(self):
        """Test validation of empty fares list."""
        stats = validate_parsed_fares([], "USD")
        assert stats["total_fares"] == 0
        assert stats["valid_fares"] == 0
        assert stats["invalid_fares"] == 0

    def test_validate_all_valid_fares(self):
        """Test validation of all valid fares."""
        fares = [
            {
                "rbd": "Y",
                "airline": "BG",
                "fare_basis": "YOWUS",
                "fare": 100.0,
                "is_rt": False,
            },
            {
                "rbd": "J",
                "airline": "BG",
                "fare_basis": "JRTUS",
                "fare": 500.0,
                "is_rt": True,
            },
        ]
        stats = validate_parsed_fares(fares, "USD")
        assert stats["total_fares"] == 2
        assert stats["valid_fares"] == 2
        assert stats["invalid_fares"] == 0

    def test_validate_mixed_valid_invalid_fares(self):
        """Test validation of mixed valid and invalid fares."""
        fares = [
            {
                "rbd": "Y",
                "airline": "BG",
                "fare_basis": "YOWUS",
                "fare": 100.0,
                "is_rt": False,
            },
            {"rbd": "J", "airline": "BG", "fare": -100.0, "is_rt": True},  # Invalid
        ]
        stats = validate_parsed_fares(fares, "USD")
        assert stats["total_fares"] == 2
        assert stats["valid_fares"] == 1
        assert stats["invalid_fares"] == 1
        assert stats["missing_fields"] == 1  # fare_basis missing

    def test_validate_with_invalid_currency(self):
        """Test validation with uncommon currency code."""
        fares = [
            {
                "rbd": "Y",
                "airline": "BG",
                "fare_basis": "YOWUS",
                "fare": 100.0,
                "is_rt": False,
            }
        ]
        stats = validate_parsed_fares(fares, "XXX")  # Uncommon currency
        # XXX has valid format, so no warnings about currency
        # But since the fare is valid, we should have 1 valid fare
        assert stats["valid_fares"] == 1


class TestCurrencyCodeList:
    """Tests for the currency code list."""

    def test_common_currencies_present(self):
        """Test that common currency codes are in the list."""
        common_currencies = ["USD", "EUR", "GBP", "JPY", "CNY", "BDT"]
        for currency in common_currencies:
            assert currency in VALID_CURRENCY_CODES

    def test_currency_codes_are_uppercase(self):
        """Test that all currency codes in the list are uppercase."""
        for code in VALID_CURRENCY_CODES:
            assert code == code.upper()
            assert len(code) == 3
