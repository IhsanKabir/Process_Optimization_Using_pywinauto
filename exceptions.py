"""
exceptions.py - Custom Exception Classes for Travelport Automation

Defines a hierarchy of exceptions for better error handling and debugging.
"""


class TravelportAutomationError(Exception):
    """Base exception for all Travelport automation errors."""

    pass


class ConnectionError(TravelportAutomationError):
    """Raised when unable to connect to Smartpoint application."""

    pass


class AuthenticationError(TravelportAutomationError):
    """Raised when login to Smartpoint fails."""

    pass


class CommandExecutionError(TravelportAutomationError):
    """Raised when a terminal command fails to execute properly."""

    def __init__(self, command: str, message: str = ""):
        self.command = command
        super().__init__(f"Command '{command}' failed: {message}")


class ParsingError(TravelportAutomationError):
    """Raised when parsing terminal output fails."""

    def __init__(self, data_type: str, message: str = ""):
        self.data_type = data_type
        super().__init__(f"Failed to parse {data_type}: {message}")


class ConfigurationError(TravelportAutomationError):
    """Raised when configuration is invalid or missing."""

    pass


class ValidationError(TravelportAutomationError):
    """Raised when input validation fails."""

    def __init__(self, field: str, value: any, message: str = ""):
        self.field = field
        self.value = value
        super().__init__(f"Invalid {field} '{value}': {message}")


class UIInteractionError(TravelportAutomationError):
    """Raised when UI interaction (clicking, typing) fails."""

    def __init__(self, action: str, element: str = "", message: str = ""):
        self.action = action
        self.element = element
        super().__init__(f"UI action '{action}' on '{element}' failed: {message}")
