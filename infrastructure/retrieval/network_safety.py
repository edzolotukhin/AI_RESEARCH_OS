from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from urllib.parse import urlparse

ResolveAddresses = Callable[[str], list[str]]


class UnsafeUrlError(ValueError):
    """Raised when a URL fails network safety checks."""

    def __init__(self, message: str, *, category: str = "unsafe_address") -> None:
        super().__init__(message)
        self.category = category


def _default_resolve_host_addresses(host: str) -> list[str]:
    """
    Resolve a hostname to IP address strings.

    IPv4-only hosts are valid even when no AAAA records exist. A failure to
    resolve one address family must not be treated as total DNS failure.
    """
    addresses: list[str] = []

    for family in (socket.AF_INET, socket.AF_INET6):
        try:
            infos = socket.getaddrinfo(
                host,
                None,
                family=family,
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror:
            continue

        for info in infos:
            addresses.append(info[4][0])

    return list(dict.fromkeys(addresses))


def _resolve_host_addresses_with_timeout(
    host: str,
    *,
    timeout_seconds: float,
) -> list[str]:
    if timeout_seconds <= 0:
        return _default_resolve_host_addresses(host)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_default_resolve_host_addresses, host)
        try:
            return future.result(timeout=timeout_seconds)
        except FuturesTimeoutError as exc:
            raise UnsafeUrlError(
                f"DNS resolution timed out for host: {host}",
                category="dns_resolution_failed",
            ) from exc


def _validate_resolved_ip(address: str) -> None:
    ip = ipaddress.ip_address(address)
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
    ):
        raise UnsafeUrlError(
            f"Destination IP {address} is not allowed for retrieval",
            category="unsafe_address",
        )


def validate_fetch_url(
    url: str,
    *,
    resolve_addresses: ResolveAddresses | None = None,
    dns_timeout_seconds: float = 5.0,
) -> None:
    """
    Reject unsafe fetch targets to reduce SSRF risk.

    Allows http/https only. Blocks localhost, private, link-local, and
    reserved IP ranges after DNS resolution.
    """
    if resolve_addresses is None:
        resolve_addresses = lambda host: _resolve_host_addresses_with_timeout(
            host,
            timeout_seconds=dns_timeout_seconds,
        )

    parsed = urlparse(url.strip())
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"}:
        raise UnsafeUrlError(
            f"Unsupported URL scheme: {scheme!r}",
            category="unsafe_address",
        )

    host = parsed.hostname
    if not host:
        raise UnsafeUrlError(
            "URL must include a hostname",
            category="unsafe_address",
        )

    lowered = host.lower()
    if lowered in {"localhost", "127.0.0.1", "::1"}:
        raise UnsafeUrlError(
            "Localhost destinations are not allowed",
            category="unsafe_address",
        )

    if lowered.endswith(".local") or lowered.endswith(".internal"):
        raise UnsafeUrlError(
            "Internal hostnames are not allowed",
            category="unsafe_address",
        )

    try:
        literal_ip = ipaddress.ip_address(host)
    except ValueError:
        literal_ip = None

    if literal_ip is not None:
        _validate_resolved_ip(str(literal_ip))
        return

    addresses = resolve_addresses(host)
    if not addresses:
        raise UnsafeUrlError(
            f"Unable to resolve host: {host}",
            category="dns_resolution_failed",
        )

    for address in addresses:
        _validate_resolved_ip(address)
