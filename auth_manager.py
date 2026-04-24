"""
auth_manager.py - Session token storage in the Windows Credential Manager.

Uses the `keyring` library backed by Windows Credential Locker (WinRT) in the
compiled exe, and the default system backend during development. Tokens are
40-character urlsafe strings issued by the live API on successful login.

Service / username constants are stable — changing them would log out all users.
"""

from __future__ import annotations

_SERVICE = "TravelportAuto"
_USERNAME = "session_token"


class KeyringUnavailableError(RuntimeError):
    """Raised by save_token when the system keyring cannot persist the token."""


def save_token(token: str) -> None:
    """Persist *token* to the system keyring.

    Raises KeyringUnavailableError if the credential store is inaccessible so
    the caller (GUI login flow) can surface the failure to the user rather than
    silently falling back to unauthenticated requests.
    """
    import keyring

    try:
        keyring.set_password(_SERVICE, _USERNAME, token)
    except Exception as exc:
        raise KeyringUnavailableError(
            "Could not save your session to the Windows Credential Manager. "
            "You may need to sign in again next launch."
        ) from exc


def get_token() -> str | None:
    """Return the stored session token, or None if not signed in."""
    import keyring

    return keyring.get_password(_SERVICE, _USERNAME) or None


def clear_token() -> None:
    """Remove the stored token (sign-out)."""
    import keyring

    try:
        keyring.delete_password(_SERVICE, _USERNAME)
    except keyring.errors.PasswordDeleteError:
        pass


def is_signed_in() -> bool:
    return get_token() is not None
