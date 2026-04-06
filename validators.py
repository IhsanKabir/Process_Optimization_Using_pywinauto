"""
validators.py - Input Validation Functions

Validates configuration, command-line arguments, and data before processing.
"""

import re
import os
import logging
from typing import Optional, List, Dict, Any
from exceptions import ValidationError, ConfigurationError

logger = logging.getLogger('travelport.validators')


def validate_airport_code(code: str, field_name: str = "airport code") -> str:
    """
    Validate that a string is a valid 3-letter IATA airport code.

    Args:
        code: The code to validate
        field_name: Name of the field for error messages

    Returns:
        Uppercase validated code

    Raises:
        ValidationError: If code is invalid
    """
    if not code:
        raise ValidationError(field_name, code, "cannot be empty")

    code = code.strip().upper()

    if not re.match(r'^[A-Z]{3}$', code):
        raise ValidationError(
            field_name,
            code,
            "must be exactly 3 letters (e.g., DAC, MLE, DOH)"
        )

    return code


def validate_airline_code(code: str) -> str:
    """
    Validate that a string is a valid 2-character airline code.

    Args:
        code: The code to validate

    Returns:
        Uppercase validated code

    Raises:
        ValidationError: If code is invalid
    """
    if not code:
        raise ValidationError("airline code", code, "cannot be empty")

    code = code.strip().upper()

    if not re.match(r'^[A-Z0-9]{2}$', code):
        raise ValidationError(
            "airline code",
            code,
            "must be exactly 2 alphanumeric characters (e.g., BG, BS, 8D)"
        )

    return code


def validate_route(route: str) -> tuple[str, str]:
    """
    Validate and parse a route string.

    Args:
        route: Route in format "DAC-MLE" or "DACMLE"

    Returns:
        Tuple of (origin, destination) airport codes

    Raises:
        ValidationError: If route is invalid
    """
    if not route:
        raise ValidationError("route", route, "cannot be empty")

    route = route.strip().upper().replace('-', '')

    if len(route) != 6:
        raise ValidationError(
            "route",
            route,
            "must be 6 letters (2 airport codes, e.g., DACMLE or DAC-MLE)"
        )

    origin = validate_airport_code(route[:3], "origin")
    dest = validate_airport_code(route[3:6], "destination")

    if origin == dest:
        raise ValidationError("route", route, "origin and destination cannot be the same")

    return origin, dest


def validate_country_code(code: str) -> str:
    """
    Validate that a string is a valid 2-letter country code.

    Args:
        code: The code to validate

    Returns:
        Uppercase validated code

    Raises:
        ValidationError: If code is invalid
    """
    if not code:
        raise ValidationError("country code", code, "cannot be empty")

    code = code.strip().upper()

    if not re.match(r'^[A-Z]{2}$', code):
        raise ValidationError(
            "country code",
            code,
            "must be exactly 2 letters (e.g., SG, MV, CN)"
        )

    return code


def validate_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate configuration dictionary structure and values.

    Args:
        config: Configuration dictionary to validate

    Returns:
        Validated config (may have defaults added)

    Raises:
        ConfigurationError: If config is invalid
    """
    # Check required keys
    required_keys = ['commands_file', 'airline_names', 'city_names', 'rbd_sort_order']
    missing = [k for k in required_keys if k not in config]
    if missing:
        raise ConfigurationError(f"Missing required config keys: {', '.join(missing)}")

    # Validate commands_file exists (if it's supposed to)
    if config.get('commands_file') and not os.path.exists(config['commands_file']):
        # This is just a warning - the file might be created later
        pass

    # Validate airline names dict
    if not isinstance(config.get('airline_names'), dict):
        raise ConfigurationError("airline_names must be a dictionary")

    for code, name in config['airline_names'].items():
        try:
            validate_airline_code(code)
        except ValidationError as e:
            raise ConfigurationError(f"Invalid airline code in airline_names: {e}")

    # Validate city names dict
    if not isinstance(config.get('city_names'), dict):
        raise ConfigurationError("city_names must be a dictionary")

    for code, name in config['city_names'].items():
        try:
            validate_airport_code(code)
        except ValidationError as e:
            raise ConfigurationError(f"Invalid airport code in city_names: {e}")

    # Validate RBD sort order
    if not isinstance(config.get('rbd_sort_order'), list):
        raise ConfigurationError("rbd_sort_order must be a list")

    for rbd in config['rbd_sort_order']:
        if not isinstance(rbd, str) or len(rbd) != 1 or not rbd.isalpha():
            raise ConfigurationError(f"Invalid RBD in rbd_sort_order: '{rbd}' (must be single letter)")

    # Validate domestic airports (add default if missing)
    if 'domestic_airports' not in config:
        config['domestic_airports'] = ['DAC']
    else:
        if not isinstance(config['domestic_airports'], list):
            raise ConfigurationError("domestic_airports must be a list")
        for code in config['domestic_airports']:
            try:
                validate_airport_code(code)
            except ValidationError as e:
                raise ConfigurationError(f"Invalid airport in domestic_airports: {e}")

    # Validate tax airports if present
    if 'tax_airports' in config:
        if not isinstance(config['tax_airports'], dict):
            raise ConfigurationError("tax_airports must be a dictionary")

        for airport_code, info in config['tax_airports'].items():
            try:
                validate_airport_code(airport_code)
            except ValidationError as e:
                raise ConfigurationError(f"Invalid airport code in tax_airports: {e}")

            if not isinstance(info, dict):
                raise ConfigurationError(f"tax_airports[{airport_code}] must be a dictionary")

            if 'country' not in info:
                raise ConfigurationError(f"tax_airports[{airport_code}] missing 'country' key")

            try:
                validate_country_code(info['country'])
            except ValidationError as e:
                raise ConfigurationError(f"Invalid country code in tax_airports[{airport_code}]: {e}")

    return config


def sanitize_command(command: str) -> str:
    """
    Sanitize a GDS terminal command to prevent injection attacks.

    Args:
        command: Raw command string

    Returns:
        Sanitized command

    Raises:
        ValidationError: If command contains dangerous characters
    """
    # Remove leading/trailing whitespace
    command = command.strip()

    # Check for suspicious characters that shouldn't be in GDS commands
    dangerous_chars = [';', '|', '&', '\n', '\r', '\x00']
    for char in dangerous_chars:
        if char in command:
            raise ValidationError(
                "command",
                command,
                f"contains prohibited character: {repr(char)}"
            )

    # Ensure command doesn't exceed reasonable length
    if len(command) > 200:
        raise ValidationError("command", command, "exceeds maximum length of 200 characters")

    return command


def validate_limit(limit: int) -> int:
    """
    Validate the --limit command-line argument.

    Args:
        limit: Limit value to validate

    Returns:
        Validated limit

    Raises:
        ValidationError: If limit is invalid
    """
    if limit < 0:
        raise ValidationError("limit", limit, "cannot be negative")

    if limit > 10000:
        raise ValidationError("limit", limit, "exceeds maximum of 10000")

    return limit


# ============================================================================
# Data Validation & Sanity Checks
# ============================================================================

# Valid currency codes (ISO 4217 - common ones used in aviation)
VALID_CURRENCY_CODES = {
    'USD', 'EUR', 'GBP', 'JPY', 'CNY', 'AUD', 'CAD', 'CHF', 'HKD', 'SGD',
    'SEK', 'KRW', 'NOK', 'NZD', 'INR', 'MXN', 'ZAR', 'BRL', 'RUB', 'THB',
    'IDR', 'MYR', 'PHP', 'VND', 'BDT', 'PKR', 'EGP', 'SAR', 'AED', 'QAR',
    'KWD', 'OMR', 'BHD', 'JOD', 'LBP', 'TRY', 'ILS', 'DKK', 'PLN', 'CZK',
    'HUF', 'RON', 'BGN', 'HRK', 'RSD', 'UAH', 'KZT', 'UZS', 'GEL', 'AMD',
    'AZN', 'TMT', 'TJS', 'KGS', 'MDL', 'BYN', 'ALL', 'MKD', 'BAM', 'ISK',
    'LKR', 'NPR', 'BTN', 'MVR', 'AFN', 'MMK', 'LAK', 'KHR', 'BND', 'PGK'
}

# Maximum reasonable fare amounts (in USD equivalent)
MAX_FARE_AMOUNT_USD = 50000  # $50,000 should cover even first-class long-haul
MAX_FARE_AMOUNT_LOCAL = 10000000  # Local currency max (e.g., 10M IDR ≈ $650)


def validate_fare_amount(
    fare: float,
    currency: Optional[str] = None,
    warn_only: bool = True
) -> bool:
    """
    Validate that a fare amount is reasonable.

    Args:
        fare: Fare amount to validate
        currency: Currency code (if known)
        warn_only: If True, log warning instead of raising exception

    Returns:
        True if valid, False if invalid

    Raises:
        ValidationError: If fare is invalid and warn_only=False
    """
    # Check if fare is positive
    if fare <= 0:
        msg = f"Fare amount {fare} must be greater than 0"
        if warn_only:
            logger.warning(f"  [VALIDATION] {msg}")
            return False
        else:
            raise ValidationError("fare", fare, "must be greater than 0")

    # Check if fare exceeds maximum reasonable amount
    max_amount = MAX_FARE_AMOUNT_USD if currency in ('USD', 'EUR', 'GBP') else MAX_FARE_AMOUNT_LOCAL
    if fare > max_amount:
        msg = f"Fare amount {fare} {currency or ''} seems unusually high (max: {max_amount})"
        if warn_only:
            logger.warning(f"  [VALIDATION] {msg}")
            return False
        else:
            raise ValidationError("fare", fare, f"exceeds maximum of {max_amount}")

    return True


def validate_currency_code(
    code: Optional[str],
    warn_only: bool = True
) -> bool:
    """
    Validate that a currency code is valid.

    Args:
        code: Currency code to validate
        warn_only: If True, log warning instead of raising exception

    Returns:
        True if valid, False if invalid

    Raises:
        ValidationError: If code is invalid and warn_only=False
    """
    if not code:
        msg = "Currency code is missing"
        if warn_only:
            logger.warning(f"  [VALIDATION] {msg}")
            return False
        else:
            raise ValidationError("currency", code, "cannot be empty")

    code = code.strip().upper()

    # Check format (3 uppercase letters)
    if not re.match(r'^[A-Z]{3}$', code):
        msg = f"Currency code '{code}' has invalid format (must be 3 letters)"
        if warn_only:
            logger.warning(f"  [VALIDATION] {msg}")
            return False
        else:
            raise ValidationError("currency", code, "must be exactly 3 letters")

    # Check if it's a known currency
    if code not in VALID_CURRENCY_CODES:
        msg = f"Currency code '{code}' is not recognized (might be valid but uncommon)"
        if warn_only:
            logger.info(f"  [VALIDATION] {msg}")
            # Don't return False - just log info as it might be a valid but uncommon currency
        else:
            raise ValidationError("currency", code, "is not a recognized currency code")

    return True


def validate_fare_data(
    fare_dict: Dict[str, Any],
    currency: Optional[str] = None,
    warn_only: bool = True
) -> List[str]:
    """
    Perform sanity checks on a fare data dictionary.

    Args:
        fare_dict: Fare dictionary to validate
        currency: Currency code (if known)
        warn_only: If True, log warnings instead of raising exceptions

    Returns:
        List of warning messages (empty if all valid)
    """
    warnings = []

    # Check for required fields
    required_fields = ['rbd', 'airline', 'fare_basis']
    for field in required_fields:
        if field not in fare_dict or not fare_dict[field]:
            msg = f"Missing required field: {field}"
            warnings.append(msg)
            if warn_only:
                logger.warning(f"  [VALIDATION] {msg}")
            else:
                raise ValidationError("fare_data", fare_dict, msg)

    # Validate fare amounts if present
    for fare_type in ['ow_fare', 'rt_fare', 'fare']:
        if fare_type in fare_dict and fare_dict[fare_type] is not None:
            if not validate_fare_amount(fare_dict[fare_type], currency, warn_only):
                warnings.append(f"Invalid {fare_type}: {fare_dict[fare_type]}")

    # Check RBD format (should be single letter)
    if 'rbd' in fare_dict and fare_dict['rbd']:
        rbd = fare_dict['rbd']
        # Handle "Y (Unsaleable)" format
        if ' (Unsaleable)' in str(rbd):
            rbd = rbd.replace(' (Unsaleable)', '')

        if len(rbd) != 1 or not rbd.isalpha():
            msg = f"RBD '{fare_dict['rbd']}' has unexpected format (should be single letter)"
            warnings.append(msg)
            if warn_only:
                logger.warning(f"  [VALIDATION] {msg}")

    return warnings


def validate_parsed_fares(
    fares: List[Dict[str, Any]],
    currency: Optional[str] = None
) -> Dict[str, Any]:
    """
    Validate a list of parsed fares and return validation statistics.

    Args:
        fares: List of fare dictionaries
        currency: Currency code for the fares

    Returns:
        Dict with validation statistics and warnings
    """
    stats = {
        'total_fares': len(fares),
        'valid_fares': 0,
        'invalid_fares': 0,
        'warnings': [],
        'missing_fields': 0
    }

    # Validate currency if provided
    if currency:
        if not validate_currency_code(currency, warn_only=True):
            stats['warnings'].append(f"Invalid or missing currency: {currency}")

    # Validate each fare
    for i, fare in enumerate(fares):
        fare_warnings = validate_fare_data(fare, currency, warn_only=True)
        if fare_warnings:
            stats['invalid_fares'] += 1
            stats['warnings'].extend([f"Fare {i+1}: {w}" for w in fare_warnings])
            if any('missing' in w.lower() for w in fare_warnings):
                stats['missing_fields'] += 1
        else:
            stats['valid_fares'] += 1

    # Log summary if there are issues
    if stats['warnings']:
        logger.warning(f"  [VALIDATION] Found {len(stats['warnings'])} validation issues in {len(fares)} fares")
        logger.debug(f"  [VALIDATION] Details: {stats}")

    return stats
