"""
google_oauth.py - Desktop PKCE Google OAuth flow for TravelportAuto sign-in.

Starts a one-shot localhost HTTP server, opens the browser to Google's consent
page, waits for the redirect callback, exchanges the auth code for an access
token, and returns the user's {email, name, sub}.

No third-party libraries required — stdlib only.
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import secrets
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
_SCOPES = "openid email profile"
_TIMEOUT_SEC = 120


class GoogleOAuthError(Exception):
    pass


@dataclass(frozen=True)
class GoogleUser:
    email: str
    name: str | None
    sub: str


def _random_string(n: int = 64) -> str:
    return secrets.token_urlsafe(n)[:n]


def _code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _exchange_code(
    code: str,
    redirect_uri: str,
    code_verifier: str,
    client_id: str,
    client_secret: str,
) -> dict:
    body = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "client_secret": client_secret,
        "code_verifier": code_verifier,
    }).encode("utf-8")
    req = urllib.request.Request(
        GOOGLE_TOKEN_URL,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise GoogleOAuthError(
            f"Token exchange failed ({exc.code}): {detail[:200]}"
        ) from exc


def _get_userinfo(access_token: str) -> dict:
    req = urllib.request.Request(
        GOOGLE_USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise GoogleOAuthError(f"Userinfo request failed: {exc.code}") from exc


def run_google_oauth_flow(client_id: str, client_secret: str) -> GoogleUser:
    """
    Runs the full PKCE OAuth flow. Blocks the calling thread until the user
    completes sign-in or the 120-second timeout expires.

    Raises GoogleOAuthError on any failure.
    """
    if not client_id:
        raise GoogleOAuthError(
            "Google Sign-In is not configured on this installation. "
            "Set GOOGLE_OAUTH_CLIENT_ID in your environment or agent_config.json."
        )
    if not client_secret:
        raise GoogleOAuthError(
            "Google Sign-In requires a client secret. "
            "Set GOOGLE_OAUTH_CLIENT_SECRET in your environment or agent_config.json."
        )

    code_verifier = _random_string(64)
    state = _random_string(16)
    port = _find_free_port()
    redirect_uri = f"http://127.0.0.1:{port}/"

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": _SCOPES,
        "state": state,
        "code_challenge": _code_challenge(code_verifier),
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "select_account",
    }
    auth_url = f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"

    callback_event = threading.Event()
    callback_result: dict = {}

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            code = (qs.get("code") or [""])[0]
            returned_state = (qs.get("state") or [""])[0]
            error = (qs.get("error") or [""])[0]

            if error:
                callback_result["error"] = error
            elif returned_state != state:
                callback_result["error"] = "State mismatch — possible CSRF."
            elif code:
                callback_result["code"] = code
            else:
                callback_result["error"] = "No authorisation code returned."

            success = "code" in callback_result
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            if success:
                html = (
                    "<h2 style='font-family:sans-serif;margin:80px auto;"
                    "max-width:420px;text-align:center'>"
                    "Signed in. You can close this tab and return to TravelportAuto.</h2>"
                )
            else:
                html = (
                    "<h2 style='font-family:sans-serif;margin:80px auto;"
                    "max-width:420px;text-align:center;color:#c0392b'>"
                    f"Error: {callback_result.get('error', 'unknown')}.<br>"
                    "Close this tab and try again.</h2>"
                )
            self.wfile.write(html.encode("utf-8"))
            callback_event.set()

        def log_message(self, *_):
            pass

    server = http.server.HTTPServer(("127.0.0.1", port), _Handler)
    server.timeout = 2

    def _serve():
        remaining = _TIMEOUT_SEC
        while not callback_event.is_set() and remaining > 0:
            server.handle_request()
            remaining -= server.timeout
        server.server_close()

    threading.Thread(target=_serve, daemon=True).start()
    webbrowser.open(auth_url)
    callback_event.wait(timeout=_TIMEOUT_SEC + 5)

    if "error" in callback_result:
        raise GoogleOAuthError(f"Google denied sign-in: {callback_result['error']}")
    if "code" not in callback_result:
        raise GoogleOAuthError("Sign-in timed out (120 s). Please try again.")

    token_data = _exchange_code(
        code=callback_result["code"],
        redirect_uri=redirect_uri,
        code_verifier=code_verifier,
        client_id=client_id,
        client_secret=client_secret,
    )
    access_token = token_data.get("access_token", "")
    if not access_token:
        raise GoogleOAuthError("No access token returned from Google.")

    userinfo = _get_userinfo(access_token)
    email = userinfo.get("email", "")
    if not email:
        raise GoogleOAuthError("Google did not return an email address.")

    return GoogleUser(
        email=email,
        name=userinfo.get("name"),
        sub=userinfo.get("sub", ""),
    )
