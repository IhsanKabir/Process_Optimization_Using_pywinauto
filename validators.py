"""
validators.py - Input Validation Functions

Validates configuration, command-line arguments, and data before processing.
"""

import re
import os
from typing import Optional, List, Dict, Any
from exceptions import ValidationError, ConfigurationError


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
