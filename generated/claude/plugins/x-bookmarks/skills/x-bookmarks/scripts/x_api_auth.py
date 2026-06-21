#!/usr/bin/env python3
# BEGIN GENERATED FROM SOURCE: packages/x-bookmarks/scripts/x_api_auth.py
# Do not edit directly; edit the source path and run make rebuild-generated.
# END GENERATED FROM SOURCE

"""Local OAuth 2.0 PKCE helper for X bookmark access."""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.server
import json
import os
from pathlib import Path
import secrets
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
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise AuthError(f"token request failed with HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise AuthError(f"token request failed: {exc.reason}") from exc

    data = json.loads(payload)
    if not isinstance(data, dict):
        raise AuthError("token endpoint returned non-object JSON")
    if "access_token" not in data:
        raise AuthError("token endpoint did not return access_token; inspect local OAuth app settings")
    return data


class OAuthCallback(http.server.BaseHTTPRequestHandler):
    server_version = "XBookmarksOAuth/1.0"

    def do_GET(self) -> None:  # noqa: N802 - stdlib hook name
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        expected_state = getattr(self.server, "expected_state")  # type: ignore[attr-defined]

        if query.get("state", [""])[0] != expected_state:
            self.server.auth_error = "state mismatch"  # type: ignore[attr-defined]
            self.respond(400, "Auth failed: state mismatch. You can close this tab.")
            return
        if "error" in query:
            message = query.get("error_description", query.get("error", ["unknown error"]))[0]
            self.server.auth_error = message  # type: ignore[attr-defined]
            self.respond(400, "Auth failed. You can close this tab.")
            return
        code = query.get("code", [""])[0]
        if not code:
            self.server.auth_error = "missing authorization code"  # type: ignore[attr-defined]
            self.respond(400, "Auth failed: missing code. You can close this tab.")
            return

        self.server.auth_code = code  # type: ignore[attr-defined]
        self.respond(200, "X bookmarks auth complete. You can close this tab.")

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


def run_auth_flow(
    client_id: str,
    client_secret: str | None,
    redirect_uri: str,
    scopes: list[str],
    open_browser: bool,
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

    server = http.server.HTTPServer(("127.0.0.1", parsed_redirect.port), OAuthCallback)
    server.expected_state = state  # type: ignore[attr-defined]
    server.auth_code = None  # type: ignore[attr-defined]
    server.auth_error = None  # type: ignore[attr-defined]

    print("Open this URL to authorize X bookmark access:")
    print(auth_url)
    if open_browser:
        webbrowser.open(auth_url)

    server.handle_request()
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
    if expires_at:
        print(f"access_token_expires_at: {time.strftime('%Y-%m-%d %H:%M:%S %z', time.localtime(int(expires_at)))}")
    return 0


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
    parser.add_argument("--include-write-scope", action="store_true", help="Also request bookmark.write.")
    parser.add_argument("--scope", action="append", default=[], help="Additional OAuth scope to request.")
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

        configured_scopes = existing_config.get("scopes")
        scopes = (
            [str(scope) for scope in configured_scopes]
            if isinstance(configured_scopes, list) and configured_scopes
            else list(DEFAULT_SCOPES)
        )
        if args.include_write_scope and "bookmark.write" not in scopes:
            scopes.append("bookmark.write")
        for scope in args.scope:
            if scope not in scopes:
                scopes.append(scope)

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
        save_config(config)
        tokens = run_auth_flow(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scopes=scopes,
            open_browser=not args.no_browser,
        )
        save_tokens(tokens)
        print(f"auth: saved local tokens to {TOKEN_FILE}")
        return 0
    except AuthError as exc:
        print(f"error: {exc}", file=sys.stderr)
        print(f"fix: inspect {CONFIG_FILE}, then rerun setup", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
