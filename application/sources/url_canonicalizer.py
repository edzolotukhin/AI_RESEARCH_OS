from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_TRACKING_PARAMS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "utm_id",
        "fbclid",
        "gclid",
        "mc_cid",
        "mc_eid",
    },
)


def canonicalize_url(url: str) -> str:
    """
    Deterministically normalize a URL for deduplication.

    Scope (conservative):
    - lowercase scheme and host
    - remove default ports (80/443)
    - remove fragments
    - remove known tracking query parameters only
    - remove trailing slash on path (except root)
    - preserve other query parameters that may identify distinct documents
    """
    parsed = urlparse(url.strip())
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid URL for canonicalization: {url!r}")

    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValueError(f"Unsupported URL scheme: {scheme!r}")

    host = parsed.hostname.lower() if parsed.hostname else ""
    port = parsed.port
    if port is not None and (
        (scheme == "http" and port == 80)
        or (scheme == "https" and port == 443)
    ):
        port = None
    netloc = host
    if port is not None:
        netloc = f"{host}:{port}"

    path = parsed.path or ""
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    filtered_pairs = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in _TRACKING_PARAMS
    ]
    filtered_pairs.sort()
    query = urlencode(filtered_pairs, doseq=True)

    return urlunparse((scheme, netloc, path, "", query, ""))


def normalize_query_text(text: str) -> str:
    """Collapse whitespace in search query text."""
    return re.sub(r"\s+", " ", text.strip())
