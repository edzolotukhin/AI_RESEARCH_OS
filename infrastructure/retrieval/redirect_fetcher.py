from __future__ import annotations

from urllib.parse import urljoin

import httpx

from infrastructure.retrieval.network_safety import UnsafeUrlError, validate_fetch_url


def fetch_with_validated_redirects(
    client: httpx.Client,
    url: str,
    *,
    max_redirects: int = 5,
    timeout: float = 10.0,
) -> httpx.Response:
    """
    Fetch a URL without automatic redirect following.

    Every redirect target is validated before the next hop is requested.
    """
    current = url
    for _ in range(max_redirects + 1):
        validate_fetch_url(current)
        response = client.get(current, follow_redirects=False, timeout=timeout)
        if response.status_code not in {301, 302, 303, 307, 308}:
            return response
        location = response.headers.get("location")
        if not location:
            raise UnsafeUrlError("Redirect response missing Location header")
        current = urljoin(current, location)
    raise UnsafeUrlError(f"Redirect limit exceeded ({max_redirects})")
