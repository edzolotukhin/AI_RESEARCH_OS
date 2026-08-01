from __future__ import annotations

API_KEY_PREFIX = "airos"


def parse_api_key(plaintext_key: str) -> tuple[str, str] | None:
    """
    Parse a presented API key format.

    Returns (key_id, plaintext_key) when valid, else None.
    """
    parts = plaintext_key.split("_", 2)
    if len(parts) != 3:
        return None
    prefix, key_id, secret = parts
    if prefix != API_KEY_PREFIX or not key_id or not secret:
        return None
    return key_id, plaintext_key
