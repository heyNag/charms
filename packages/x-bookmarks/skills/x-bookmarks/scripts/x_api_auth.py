#!/usr/bin/env python3
"""Local OAuth 2.0 PKCE helper for X bookmark access."""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import http.client
import http.server
import json
import os
from pathlib import Path
import secrets
import socketserver
import sys
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

AUTHORIZE_URL = "https://x.com/i/oauth2/authorize"
TOKEN_URL = "https://api.x.com/2/oauth2/token"
DEFAULT_REDIRECT_URI = "http://localhost:8739/callback"
DEFAULT_SCOPES = ["tweet.read", "users.read", "bookmark.read", "offline.access"]
# OAuth 2.0 scopes documented by X; anything else is a typo X would reject.
KNOWN_SCOPES = frozenset(
    {
        "block.read",
        "block.write",
        "bookmark.read",
        "bookmark.write",
        "dm.read",
        "dm.write",
        "follows.read",
        "follows.write",
        "like.read",
        "like.write",
        "list.read",
        "list.write",
        "media.write",
        "mute.read",
        "mute.write",
        "offline.access",
        "space.read",
        "tweet.moderate.write",
        "tweet.read",
        "tweet.write",
        "users.email",
        "users.read",
    }
)
# How long setup waits for the browser to return to the local callback.
CALLBACK_TIMEOUT_SECONDS = 300

CONFIG_DIR = Path(os.environ.get("X_BOOKMARKS_CONFIG_DIR", "~/.config/x-bookmarks")).expanduser()
CONFIG_FILE = CONFIG_DIR / "config.json"
TOKEN_FILE = Path(os.environ.get("X_BOOKMARKS_TOKEN_FILE", str(CONFIG_DIR / "tokens.json"))).expanduser()


class AuthError(RuntimeError):
    """Raised for OAuth setup and token refresh failures."""


def now() -> int:
    return int(time.time())


def private_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    os.chmod(path, 0o600)


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise AuthError(f"{path} must contain a JSON object")
    return value


def load_config() -> dict[str, Any]:
    if not CONFIG_FILE.exists():
        raise AuthError(f"missing config: {CONFIG_FILE}")
    return read_json(CONFIG_FILE)


def load_tokens() -> dict[str, Any]:
    if not TOKEN_FILE.exists():
        raise AuthError(f"missing tokens: {TOKEN_FILE}")
    return read_json(TOKEN_FILE)


def save_config(config: dict[str, Any]) -> None:
    private_write_json(CONFIG_FILE, config)


def save_tokens(tokens: dict[str, Any]) -> None:
    private_write_json(TOKEN_FILE, tokens)


def add_token_metadata(tokens: dict[str, Any], scopes: list[str]) -> dict[str, Any]:
    stamped = dict(tokens)
    stamped["created_at"] = now()
    if "expires_in" in stamped:
        stamped["expires_at"] = now() + int(stamped["expires_in"])
    stamped["scope_list"] = scopes
    return stamped


class RefuseRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects so credentials are never resent to another URL."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        fp.close()
        raise urllib.error.URLError(f"refused HTTP {code} redirect to {newurl}")


def open_request(request: urllib.request.Request, timeout: float) -> Any:
    """Open an authenticated request; X API endpoints never redirect."""
    return urllib.request.build_opener(RefuseRedirect).open(request, timeout=timeout)


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def token_request(
    form: dict[str, str],
    client_id: str,
    client_secret: str | None = None,
) -> dict[str, Any]:
    body = dict(form)
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if client_secret:
        auth = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {auth}"
    else:
        body["client_id"] = client_id

    request = urllib.request.Request(
        TOKEN_URL,
        data=urllib.parse.urlencode(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with open_request(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except (http.client.HTTPException, OSError):
            detail = "unreadable response body"
        finally:
            exc.close()
        raise AuthError(f"token request failed with HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise AuthError(f"token request failed: {exc.reason}") from exc
    except (http.client.HTTPException, OSError) as exc:
        # The connection dropped or the body was cut short after the headers.
        raise AuthError(f"token request failed: {exc}") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise AuthError(f"token endpoint returned invalid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise AuthError("token endpoint returned non-object JSON")
    if "access_token" not in data:
        raise AuthError("token endpoint did not return access_token; inspect local OAuth app settings")
    return data


class OAuthCallback(http.server.BaseHTTPRequestHandler):
    server_version = "XBookmarksOAuth/1.0"
    # Let a handler thread drop a connection that stops sending.
    timeout = 10

    def do_GET(self) -> None:  # noqa: N802 - stdlib hook name
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        expected_path = getattr(self.server, "expected_path")  # type: ignore[attr-defined]
        expected_state = getattr(self.server, "expected_state")  # type: ignore[attr-defined]

        # Stray requests (favicon, probes, an old tab from an earlier run) do
        # not belong to this flow, so answer them and keep waiting.
        if parsed.path != expected_path:
            self.respond(404, "Not found.")
            return
        if query.get("state", [""])[0] != expected_state:
            self.server.rejected = "state mismatch"  # type: ignore[attr-defined]
            self.respond(400, "Auth failed: state mismatch. You can close this tab.")
            return
        if "error" in query:
            message = query.get("error_description", query.get("error", ["unknown error"]))[0]
            self.conclude(400, "Auth failed. You can close this tab.", error=message)
            return
        code = query.get("code", [""])[0]
        if not code:
            self.conclude(
                400, "Auth failed: missing code. You can close this tab.", error="missing authorization code"
            )
            return

        self.conclude(200, "X bookmarks auth complete. You can close this tab.", code=code)

    def conclude(
        self, status: int, message: str, code: str | None = None, error: str | None = None
    ) -> None:
        """Write the page, then hand the flow its result.

        The process may exit as soon as the flow sees a result, which ends this
        daemon thread, so the page goes out first. A browser that hung up
        before reading it does not void the result.
        """
        with contextlib.suppress(OSError):
            self.respond(status, message)
        if error is not None:
            self.server.auth_error = error  # type: ignore[attr-defined]
        else:
            self.server.auth_code = code  # type: ignore[attr-defined]

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def respond(self, status: int, message: str) -> None:
        body = (
            "<!doctype html><html><head><meta charset=\"utf-8\">"
            "<title>X bookmarks auth</title></head>"
            f"<body><p>{message}</p></body></html>"
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class CallbackServer(http.server.ThreadingHTTPServer):
    """Loopback server for the OAuth callback.

    Each request runs on a daemon thread, so a slow client can neither hold
    the flow past its deadline nor keep the process alive after it.
    """

    daemon_threads = True

    def server_bind(self) -> None:
        # HTTPServer.server_bind resolves the host's FQDN, a reverse DNS lookup
        # that can stall setup for seconds on macOS; loopback needs no name.
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = port


def run_auth_flow(
    client_id: str,
    client_secret: str | None,
    redirect_uri: str,
    scopes: list[str],
    open_browser: bool,
    timeout: float = CALLBACK_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    parsed_redirect = urllib.parse.urlparse(redirect_uri)
    if parsed_redirect.hostname not in {"localhost", "127.0.0.1"}:
        raise AuthError("redirect URI must use localhost or 127.0.0.1 for the local helper")
    if not parsed_redirect.port:
        raise AuthError("redirect URI must include a port")

    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(32)
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": " ".join(scopes),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    auth_url = AUTHORIZE_URL + "?" + urllib.parse.urlencode(params)

    address = ("127.0.0.1", parsed_redirect.port)
    try:
        server = CallbackServer(address, OAuthCallback)
    except OSError as exc:
        raise AuthError(
            f"cannot listen on {redirect_uri}: {exc.strerror or exc}; stop the other setup run "
            "or pass --redirect-uri with a free loopback port registered in the X app"
        ) from exc
    server.expected_path = parsed_redirect.path or "/"  # type: ignore[attr-defined]
    server.expected_state = state  # type: ignore[attr-defined]
    server.auth_code = None  # type: ignore[attr-defined]
    server.auth_error = None  # type: ignore[attr-defined]
    server.rejected = None  # type: ignore[attr-defined]
    # handle_request() returns once it hands a connection to a thread, or after
    # this many idle seconds, so the deadline below is checked even when
    # nothing connects.
    server.timeout = min(1.0, timeout)

    print("Open this URL to authorize X bookmark access:")
    # Flush now: piped stdout is block-buffered and the wait below can last minutes.
    print(auth_url, flush=True)
    if open_browser:
        webbrowser.open(auth_url)

    deadline = time.monotonic() + timeout
    try:
        while server.auth_code is None and server.auth_error is None:  # type: ignore[attr-defined]
            if time.monotonic() >= deadline:
                rejected = getattr(server, "rejected", None)
                detail = f" (last callback rejected: {rejected})" if rejected else ""
                raise AuthError(
                    f"no OAuth callback on {redirect_uri} within {timeout:g}s{detail}; "
                    "rerun setup and approve access in the browser"
                )
            server.handle_request()
    finally:
        server.server_close()
    auth_error = getattr(server, "auth_error", None)
    if auth_error:
        raise AuthError(str(auth_error))
    code = getattr(server, "auth_code", None)
    if not code:
        raise AuthError("authorization did not complete")

    tokens = token_request(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
        },
        client_id=client_id,
        client_secret=client_secret,
    )
    return add_token_metadata(tokens, scopes)


def refresh_tokens(config: dict[str, Any], tokens: dict[str, Any]) -> dict[str, Any]:
    refresh_token = tokens.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        raise AuthError("missing refresh_token; rerun setup")
    client_id = str(config.get("client_id", ""))
    if not client_id:
        raise AuthError("missing client_id in config; rerun setup")
    client_secret = config.get("client_secret") or os.environ.get("X_API_CLIENT_SECRET")
    scopes = [str(item) for item in config.get("scopes", DEFAULT_SCOPES)]

    refreshed = token_request(
        {"grant_type": "refresh_token", "refresh_token": refresh_token},
        client_id=client_id,
        client_secret=str(client_secret) if client_secret else None,
    )
    if "refresh_token" not in refreshed:
        refreshed["refresh_token"] = refresh_token
    stamped = add_token_metadata(refreshed, scopes)
    save_tokens(stamped)
    return stamped


def get_valid_token(force_refresh: bool = False) -> str:
    env_token = os.environ.get("X_API_ACCESS_TOKEN") or os.environ.get("X_API_BEARER_TOKEN")
    if env_token:
        return env_token

    config = load_config()
    tokens = load_tokens()
    access_token = tokens.get("access_token")
    expires_at = int(tokens.get("expires_at", 0) or 0)

    if force_refresh or not access_token or (expires_at and expires_at <= now() + 120):
        tokens = refresh_tokens(config, tokens)
        access_token = tokens.get("access_token")

    if not isinstance(access_token, str) or not access_token:
        raise AuthError("missing access_token; rerun setup")
    return access_token


def status() -> int:
    print(f"config: {CONFIG_FILE}")
    print(f"tokens: {TOKEN_FILE}")
    if not CONFIG_FILE.exists():
        print("auth: missing config")
        return 1
    if not TOKEN_FILE.exists():
        print("auth: missing tokens")
        return 1
    config = load_config()
    tokens = load_tokens()
    scopes = " ".join(str(item) for item in config.get("scopes", []))
    expires_at = tokens.get("expires_at")
    print("auth: configured")
    print(f"scopes: {scopes or 'unknown'}")
    extra = [str(item) for item in config.get("scopes", []) if str(item) not in DEFAULT_SCOPES]
    if extra:
        print(
            f"warning: scopes beyond the read-only defaults: {' '.join(extra)}; "
            "rerun setup without --include-write-scope or --scope to drop them"
        )
    if expires_at:
        print(f"access_token_expires_at: {time.strftime('%Y-%m-%d %H:%M:%S %z', time.localtime(int(expires_at)))}")
    return 0


def requested_scopes(include_write_scope: bool, extra_scopes: list[str]) -> list[str]:
    """Return the read-only defaults plus only the scopes this run asks for.

    Saved scopes are never reused: one write-scope setup must not carry
    bookmark.write into every later read-only setup.
    """
    scopes = list(DEFAULT_SCOPES)
    if include_write_scope:
        extra_scopes = ["bookmark.write", *extra_scopes]
    for scope in extra_scopes:
        if scope not in KNOWN_SCOPES:
            known = " ".join(sorted(KNOWN_SCOPES))
            raise AuthError(f"unknown OAuth scope {scope!r}; use one of: {known}")
        if scope not in scopes:
            scopes.append(scope)
    return scopes


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Set up local X API v2 OAuth for x-bookmarks.")
    parser.add_argument("--client-id", help="X OAuth 2.0 client ID.")
    parser.add_argument("--client-secret", help="Optional X OAuth 2.0 client secret for confidential clients.")
    parser.add_argument(
        "--client-secret-stdin",
        action="store_true",
        help="Read the X OAuth 2.0 client secret from stdin without printing it.",
    )
    parser.add_argument("--redirect-uri", help=f"OAuth callback URL. Defaults to {DEFAULT_REDIRECT_URI}.")
    parser.add_argument(
        "--include-write-scope",
        action="store_true",
        help="Also request bookmark.write for this setup only.",
    )
    parser.add_argument(
        "--scope",
        action="append",
        default=[],
        help="Additional OAuth scope to request for this setup only (repeatable).",
    )
    parser.add_argument("--no-browser", action="store_true", help="Print URL without opening the browser.")
    parser.add_argument("--refresh", action="store_true", help="Refresh the local token without printing it.")
    parser.add_argument("--status", action="store_true", help="Show local auth status without printing tokens.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        if args.status:
            return status()
        if args.refresh:
            refresh_tokens(load_config(), load_tokens())
            print("auth: refreshed")
            return 0
        if args.client_secret and args.client_secret_stdin:
            raise AuthError("use either --client-secret or --client-secret-stdin, not both")

        existing_config: dict[str, Any] = {}
        if CONFIG_FILE.exists():
            existing_config = load_config()

        client_id = args.client_id or existing_config.get("client_id")
        if not isinstance(client_id, str) or not client_id:
            raise AuthError(f"missing client_id; fill {CONFIG_FILE} or pass --client-id")

        scopes = requested_scopes(args.include_write_scope, args.scope)

        client_secret = args.client_secret or existing_config.get("client_secret")
        if args.client_secret_stdin:
            client_secret = sys.stdin.readline().strip()
            if not client_secret:
                raise AuthError("client secret from stdin was empty")
        if not isinstance(client_secret, str):
            client_secret = None

        redirect_uri = args.redirect_uri or str(existing_config.get("redirect_uri") or DEFAULT_REDIRECT_URI)

        config = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scopes": scopes,
        }
        if client_secret:
            config["client_secret"] = client_secret
        tokens = run_auth_flow(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scopes=scopes,
            open_browser=not args.no_browser,
        )
        # Save config only with the tokens it produced, so a failed run cannot
        # leave scopes behind that no token was granted for.
        save_config(config)
        save_tokens(tokens)
        print(f"auth: saved local tokens to {TOKEN_FILE}")
        return 0
    except AuthError as exc:
        print(f"error: {exc}", file=sys.stderr)
        print(f"fix: inspect {CONFIG_FILE}, then rerun setup", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
