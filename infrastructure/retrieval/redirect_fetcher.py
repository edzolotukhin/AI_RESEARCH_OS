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
    dns_timeout_seconds: float = 5.0,
    navigation_budget=None,
) -> httpx.Response:
    """
    Fetch a URL without automatic redirect following.

    Every redirect target is validated before the next hop is requested.
    """
    current = url
    redirect_chain = []
    for _ in range(max_redirects + 1):
        validate_fetch_url(current, dns_timeout_seconds=dns_timeout_seconds)
        redirect_chain.append(current)
        if navigation_budget is not None:
            navigation_budget.request(current)
        if navigation_budget is not None and isinstance(client, httpx.Client):
            with client.stream("GET", current, follow_redirects=False, timeout=timeout) as streamed:
                parts = []
                for part in streamed.iter_bytes(chunk_size=8192):
                    navigation_budget.receive(len(part))
                    parts.append(part)
                headers = dict(streamed.headers)
                # iter_bytes has already decoded the transport encoding.
                for name in ("content-encoding", "content-length", "transfer-encoding"):
                    headers.pop(name, None)
                response = httpx.Response(streamed.status_code, headers=headers,
                                          content=b"".join(parts), request=streamed.request)
        else:
            response = client.get(current, follow_redirects=False, timeout=timeout)
            if navigation_budget is not None:
                navigation_budget.receive(len(response.content))
        if navigation_budget is not None:
            navigation_budget.event(url=current, http_status=response.status_code)
        if response.status_code not in {301, 302, 303, 307, 308}:
            if isinstance(response, httpx.Response):
                response.extensions["validated_redirect_chain"] = tuple(redirect_chain)
            return response
        location = response.headers.get("location")
        if not location:
            raise UnsafeUrlError("Redirect response missing Location header")
        current = urljoin(current, location)
    raise UnsafeUrlError(f"Redirect limit exceeded ({max_redirects})")
