"""
Tests for auth_manager — keyring wrapper for session tokens.
All tests inject a fake keyring via sys.modules so no real credentials are touched.
"""

import sys
import types

import pytest


class _FakePasswordDeleteError(Exception):
    pass


class _FakeKeyring:
    """In-memory keyring stub."""

    def __init__(self):
        self._store: dict[tuple, str] = {}
        self.errors = types.SimpleNamespace(PasswordDeleteError=_FakePasswordDeleteError)

    def get_password(self, service, username):
        return self._store.get((service, username))

    def set_password(self, service, username, password):
        self._store[(service, username)] = password

    def delete_password(self, service, username):
        key = (service, username)
        if key not in self._store:
            raise _FakePasswordDeleteError()
        del self._store[key]


@pytest.fixture(autouse=True)
def mock_keyring():
    """Inject a fresh in-memory keyring for each test."""
    fake = _FakeKeyring()
    sys.modules["keyring"] = fake  # type: ignore[assignment]
    yield fake
    sys.modules.pop("keyring", None)


def test_save_and_get_token_roundtrip():
    from auth_manager import get_token, save_token

    save_token("abc123")
    assert get_token() == "abc123"


def test_get_token_returns_none_when_empty():
    from auth_manager import get_token

    assert get_token() is None


def test_clear_token_removes_stored_value():
    from auth_manager import clear_token, get_token, save_token

    save_token("tok-xyz")
    clear_token()
    assert get_token() is None


def test_clear_token_does_not_raise_when_nothing_stored():
    from auth_manager import clear_token

    clear_token()  # no token stored — should not raise


def test_is_signed_in_false_when_no_token():
    from auth_manager import is_signed_in

    assert is_signed_in() is False


def test_is_signed_in_true_after_save():
    from auth_manager import is_signed_in, save_token

    save_token("live-token")
    assert is_signed_in() is True


def test_save_overwrites_previous_token():
    from auth_manager import get_token, save_token

    save_token("first")
    save_token("second")
    assert get_token() == "second"


def test_service_and_username_constants_are_stable():
    """Changing these constants would log out all users — pin the values."""
    import auth_manager

    assert auth_manager._SERVICE == "TravelportAuto"
    assert auth_manager._USERNAME == "session_token"


def test_save_token_raises_keyring_unavailable_on_failure():
    """save_token must raise KeyringUnavailableError (not swallow) when keyring errors."""
    import sys
    import types

    broken = types.SimpleNamespace(
        get_password=lambda *a: None,
        set_password=lambda *a: (_ for _ in ()).throw(RuntimeError("credential store locked")),
        delete_password=lambda *a: None,
        errors=types.SimpleNamespace(PasswordDeleteError=Exception),
    )
    sys.modules["keyring"] = broken  # type: ignore[assignment]

    from auth_manager import KeyringUnavailableError, save_token

    with pytest.raises(KeyringUnavailableError):
        save_token("some-token")

    sys.modules.pop("keyring", None)
