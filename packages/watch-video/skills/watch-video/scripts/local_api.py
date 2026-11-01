"""A loopback-only OpenAI-compatible client for local media inference."""

from __future__ import annotations

import ipaddress
import json
import math
import os
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from local_config import get_setting, resolve_api_key


DEFAULT_BASE_URL = "http://127.0.0.1:8147/v1"
MAX_RESPONSE_BYTES = 16 * 1024 * 1024


class LocalAPIError(RuntimeError):
    """Safe-to-record local service error; contains no server response body."""

    def __init__(self, message, *, http_status=None, stop_remaining_chunks=True):
        super().__init__(message)
        self.http_status = http_status
        self.stop_remaining_chunks = stop_remaining_chunks


def validate_base_url(value: str | None = None) -> str:
    """Normalize a literal loopback endpoint, never resolving a remote hostname.

    ``localhost`` is pinned to 127.0.0.1 instead of relying on host DNS or proxies.
    Use an explicit [::1] URL for an IPv6-only local listener.
    """
    value = value or os.environ.get("WATCH_VIDEO_LOCAL_BASE_URL") or DEFAULT_BASE_URL
    try:
        if not isinstance(value, str) or any(ord(c) <= 32 for c in value):
            raise ValueError
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https"} or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment):
            raise ValueError
        host = parsed.hostname or ""
        if host.lower() in {"localhost", "localhost."}:
            host = "127.0.0.1"
        address = ipaddress.ip_address(host)
        if not address.is_loopback or "%" in host or getattr(address, "ipv4_mapped", None):
            raise ValueError
        port = parsed.port
        if port is not None and not 1 <= port <= 65535:
            raise ValueError
        path = parsed.path.rstrip("/") or "/v1"
        if path != "/v1":
            raise ValueError
        host = f"[{address}]" if address.version == 6 else str(address)
        netloc = f"{host}:{port}" if port is not None else host
        return urlunsplit((parsed.scheme, netloc, path, "", ""))
    except (TypeError, ValueError):
        raise ValueError(
            "Local API base URL must use http(s), a loopback IP or localhost, "
            "and /v1, without credentials, query, or fragment."
        ) from None


class _RefuseRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(req.full_url, code, "redirect refused", headers, fp)


def redact_secrets(value, secret: str):
    """Remove an echoed credential before any response can become an artifact."""
    if not secret:
        return value
    if isinstance(value, str):
        return value.replace(secret, "[REDACTED]")
    if isinstance(value, list):
        return [redact_secrets(item, secret) for item in value]
    if isinstance(value, dict):
        return {redact_secrets(key, secret): redact_secrets(item, secret)
                for key, item in value.items()}
    return value


class LocalClient:
    def __init__(self, base_url=None, api_key=None, timeout=600):
        configured_url = base_url if base_url is not None else get_setting("WATCH_VIDEO_LOCAL_BASE_URL")
        self.base_url = validate_base_url(configured_url)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) \
                or not math.isfinite(timeout) or not 0 < timeout <= 3600:
            raise ValueError("Local API timeout must be between 0 and 3600 seconds.")
        self.timeout = timeout
        self._api_key = resolve_api_key(api_key)
        # Disable both environment and macOS system proxies; never send local
        # media or the credential through an HTTP(S) proxy.
        self._opener = build_opener(ProxyHandler({}), _RefuseRedirects())

    def request_json(self, path, payload=None, *, method=None, body=None, content_type=None):
        # Joining an arbitrary URL could escape the origin. Only relative API
        # endpoint paths are accepted, with no query/fragment or traversal.
        if not isinstance(path, str) or not path or path.startswith("//"):
            raise ValueError("Local API endpoint must be a relative path.")
        endpoint = path.lstrip("/")
        if any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-/"
               for c in endpoint) or not endpoint or "//" in endpoint \
                or any(part in {".", ".."} for part in endpoint.split("/")):
            raise ValueError("Local API endpoint must be a relative path.")
        if payload is not None and body is not None:
            raise ValueError("Provide either JSON payload or raw body, not both.")
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
            content_type = "application/json"
        headers = {"User-Agent": "charms-watch-video/0.1", "Accept": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        if content_type:
            headers["Content-Type"] = content_type
        request = Request(self.base_url + "/" + endpoint, data=body, headers=headers,
                          method=method or ("POST" if body is not None else "GET"))
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise LocalAPIError("Local API response exceeds the 16 MiB response limit.")
            try:
                data = json.loads(raw)
            except (ValueError, UnicodeError):
                raise LocalAPIError("Local API returned an invalid JSON response.") from None
            if not isinstance(data, dict):
                raise LocalAPIError("Local API returned a non-object JSON response.")
            return redact_secrets(data, self._api_key)
        except HTTPError as exc:
            status = exc.code
            exc.close()
            reason = "redirect refused" if 300 <= status < 400 else "request rejected"
            # Response bodies and urllib exceptions can echo uploaded content,
            # Authorization, URLs, or credentials. Persist only a status code.
            raise LocalAPIError(f"Local API {reason} (HTTP {status}).",
                                http_status=status,
                                stop_remaining_chunks=True) from None
        except HTTPException:
            # IncompleteRead and other HTTP framing failures are not OSError.
            # Do not expose their partial body or malformed status/header text.
            raise LocalAPIError(
                "Local API response was interrupted or malformed; check the local server before resuming."
            ) from None
        except (URLError, TimeoutError, OSError):
            raise LocalAPIError(
                "Local API connection failed or timed out; check that the local server is running."
            ) from None

    def get_models(self):
        return self.request_json("models")


def request_json(path, payload=None, *, base_url=None, api_key=None, timeout=600,
                 method=None, body=None, content_type=None):
    return LocalClient(base_url, api_key, timeout).request_json(
        path, payload, method=method, body=body, content_type=content_type,
    )
