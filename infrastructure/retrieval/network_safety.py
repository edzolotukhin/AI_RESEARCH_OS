from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeUrlError(ValueError):
    """Raised when a URL fails network safety checks."""


def validate_fetch_url(url: str) -> None:
    """
    Reject unsafe fetch targets to reduce SSRF risk.

    Allows http/https only. Blocks localhost, private, link-local, and
    reserved IP ranges after DNS resolution.
    """
    parsed = urlparse(url.strip())
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"}:
        raise UnsafeUrlError(f"Unsupported URL scheme: {scheme!r}")

    host = parsed.hostname
    if not host:
        raise UnsafeUrlError("URL must include a hostname")

    lowered = host.lower()
    if lowered in {"localhost", "127.0.0.1", "::1"}:
        raise UnsafeUrlError("Localhost destinations are not allowed")

    if lowered.endswith(".local") or lowered.endswith(".internal"):
        raise UnsafeUrlError("Internal hostnames are not allowed")

    for family in (socket.AF_INET, socket.AF_INET6):
        try:
            infos = socket.getaddrinfo(host, None, family=family)
        except socket.gaierror as exc:
            raise UnsafeUrlError(f"Unable to resolve host: {host}") from exc
        for info in infos:
            address = info[4][0]
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
                )
