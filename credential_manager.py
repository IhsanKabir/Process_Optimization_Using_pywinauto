"""
credential_manager.py - Secure Credential Management

Handles credentials securely using environment variables instead of command-line arguments.
Supports .env files for local development.
"""

import os
from typing import Optional, Tuple
from exceptions import AuthenticationError, ConfigurationError


class CredentialManager:
    """Manages secure retrieval of Smartpoint credentials."""

    # Environment variable names
    ENV_USERNAME = "SMARTPOINT_USERNAME"
    ENV_PASSWORD = "SMARTPOINT_PASSWORD"
    ENV_PCC = "SMARTPOINT_PCC"

    @staticmethod
    def load_from_env() -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Load credentials from environment variables.

        Returns:
            Tuple of (username, password, pcc) or (None, None, None) if not set

        Note:
            Reads from:
            - SMARTPOINT_USERNAME
            - SMARTPOINT_PASSWORD
            - SMARTPOINT_PCC (optional)
        """
        username = os.getenv(CredentialManager.ENV_USERNAME)
        password = os.getenv(CredentialManager.ENV_PASSWORD)
        pcc = os.getenv(CredentialManager.ENV_PCC)

        # Only return if both username and password are set
        if username and password:
            return username, password, pcc
        elif username or password:
            # Partial credentials - warn user
            return None, None, None
        else:
            return None, None, None

    @staticmethod
    def validate_credentials(
        username: str, password: str, pcc: Optional[str] = None
    ) -> bool:
        """
        Validate that credentials meet basic requirements.

        Args:
            username: Smartpoint username
            password: Smartpoint password
            pcc: Optional Pseudo City Code

        Returns:
            True if credentials are valid

        Raises:
            AuthenticationError: If credentials are invalid
        """
        if not username or not username.strip():
            raise AuthenticationError("Username cannot be empty")

        if not password or not password.strip():
            raise AuthenticationError("Password cannot be empty")

        # Basic length checks
        if len(username) < 3:
            raise AuthenticationError("Username too short (minimum 3 characters)")

        if len(password) < 4:
            raise AuthenticationError("Password too short (minimum 4 characters)")

        # PCC validation if provided
        if pcc:
            if not pcc.strip():
                raise AuthenticationError("PCC cannot be empty if provided")
            if len(pcc.strip()) > 10:
                raise AuthenticationError("PCC too long (maximum 10 characters)")

        return True

    @staticmethod
    def get_credentials(
        force_env: bool = False,
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Get credentials with fallback strategy.

        Args:
            force_env: If True, only use environment variables

        Returns:
            Tuple of (username, password, pcc)

        Note:
            Priority order:
            1. Environment variables (SMARTPOINT_USERNAME, SMARTPOINT_PASSWORD, SMARTPOINT_PCC)
            2. Returns (None, None, None) if not found
        """
        # Try environment variables first
        username, password, pcc = CredentialManager.load_from_env()

        if username and password:
            try:
                CredentialManager.validate_credentials(username, password, pcc)
                return username, password, pcc
            except AuthenticationError:
                # Invalid credentials in environment
                return None, None, None

        return None, None, None

    @staticmethod
    def setup_instructions() -> str:
        """
        Return instructions for setting up credentials.

        Returns:
            Multi-line string with setup instructions
        """
        return f"""
Credential Setup Instructions
{'='*60}

For secure credential management, set environment variables:

Windows (PowerShell):
  $env:{CredentialManager.ENV_USERNAME}="your_username"
  $env:{CredentialManager.ENV_PASSWORD}="your_password"
  $env:{CredentialManager.ENV_PCC}="your_pcc"  # Optional

Windows (Command Prompt):
  set {CredentialManager.ENV_USERNAME}=your_username
  set {CredentialManager.ENV_PASSWORD}=your_password
  set {CredentialManager.ENV_PCC}=your_pcc  # Optional

Or create a .env file in the project directory:
  {CredentialManager.ENV_USERNAME}=your_username
  {CredentialManager.ENV_PASSWORD}=your_password
  {CredentialManager.ENV_PCC}=your_pcc  # Optional

Then load it with: pip install python-dotenv
And add at the top of your script: from dotenv import load_dotenv; load_dotenv()

IMPORTANT: Never commit credentials to version control!
The .env file is already in .gitignore for your protection.
{'='*60}
"""
