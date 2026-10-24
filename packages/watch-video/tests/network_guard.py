"""Suite-wide guard: unit tests must never reach a real network host.

Every test module starts it from setUpModule. While it is installed, a
non-loopback host passed to socket.getaddrinfo, gethostbyname,
gethostbyname_ex, gethostbyaddr or getnameinfo, or a non-loopback IPv4 or
IPv6 address passed to a socket's connect, connect_ex, sendto or sendmsg,
raises AssertionError. urllib and the scripts' retry loops do not catch it,
so an accidental real request (for example one carrying a stored API key)
fails loudly. Loopback stays open for local fake servers.

urllib proxies are switched off too. A loopback proxy, from *_proxy env vars
or a macOS system proxy (urllib reads both), would otherwise pass the
loopback check and tunnel the request to the real host.

The patches cover the test process only. A test that runs a script in a
child process keeps that child offline itself, as the offline pipeline test
does with a fake yt-dlp on PATH and --transcriber none.
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.request
from unittest import mock


_REAL_GETADDRINFO = socket.getaddrinfo
_REAL_GETHOSTBYNAME = socket.gethostbyname
_REAL_GETHOSTBYNAME_EX = socket.gethostbyname_ex
_REAL_GETHOSTBYADDR = socket.gethostbyaddr
_REAL_GETNAMEINFO = socket.getnameinfo
_REAL_CONNECT = socket.socket.connect
_REAL_CONNECT_EX = socket.socket.connect_ex
_REAL_SENDTO = socket.socket.sendto
_REAL_SENDMSG = getattr(socket.socket, "sendmsg", None)
_PATCHERS: list = []


def _is_loopback(host: object) -> bool:
    if host is None:
        return True
    if isinstance(host, bytes):
        host = host.decode("ascii", errors="replace")
    name = str(host).strip("[]").lower()
    if name in {"", "localhost", "localhost."}:
        return True
    try:
        return ipaddress.ip_address(name.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def _blocked(target: object) -> AssertionError:
    return AssertionError(f"unit tests must not reach the network: {target!r}")


def _check_host(host: object) -> None:
    if not _is_loopback(host):
        raise _blocked(host)


def _getaddrinfo(host, *args, **kwargs):
    _check_host(host)
    return _REAL_GETADDRINFO(host, *args, **kwargs)


def _gethostbyname(host):
    _check_host(host)
    return _REAL_GETHOSTBYNAME(host)


def _gethostbyname_ex(host):
    _check_host(host)
    return _REAL_GETHOSTBYNAME_EX(host)


def _gethostbyaddr(host):
    _check_host(host)
    return _REAL_GETHOSTBYADDR(host)


def _getnameinfo(sockaddr, flags):
    _check_host(sockaddr[0] if isinstance(sockaddr, tuple) else sockaddr)
    return _REAL_GETNAMEINFO(sockaddr, flags)


def _check_address(sock: socket.socket, address: object) -> None:
    if sock.family in (socket.AF_INET, socket.AF_INET6):
        host = address[0] if isinstance(address, tuple) else address
        if not _is_loopback(host):
            raise _blocked(address)


def _connect(self, address):
    _check_address(self, address)
    return _REAL_CONNECT(self, address)


def _connect_ex(self, address):
    _check_address(self, address)
    return _REAL_CONNECT_EX(self, address)


def _sendto(self, *args):
    # sendto(data, address) or sendto(data, flags, address).
    _check_address(self, args[-1])
    return _REAL_SENDTO(self, *args)


def _sendmsg(self, *args):
    # sendmsg(buffers[, ancdata[, flags[, address]]]); no address means the
    # socket's connected peer, which connect already checked.
    if len(args) >= 4 and args[3] is not None:
        _check_address(self, args[3])
    return _REAL_SENDMSG(self, *args)


def install() -> None:
    if _PATCHERS:
        return
    patchers = [
        mock.patch.object(socket, "getaddrinfo", _getaddrinfo),
        mock.patch.object(socket, "gethostbyname", _gethostbyname),
        mock.patch.object(socket, "gethostbyname_ex", _gethostbyname_ex),
        mock.patch.object(socket, "gethostbyaddr", _gethostbyaddr),
        mock.patch.object(socket, "getnameinfo", _getnameinfo),
        mock.patch.object(socket.socket, "connect", _connect),
        mock.patch.object(socket.socket, "connect_ex", _connect_ex),
        mock.patch.object(socket.socket, "sendto", _sendto),
        # ProxyHandler reads this when an opener is built; {} means no proxy.
        mock.patch.object(urllib.request, "getproxies", dict),
    ]
    if _REAL_SENDMSG is not None:
        patchers.append(mock.patch.object(socket.socket, "sendmsg", _sendmsg))
    for patcher in patchers:
        patcher.start()
        _PATCHERS.append(patcher)


def uninstall() -> None:
    while _PATCHERS:
        _PATCHERS.pop().stop()
