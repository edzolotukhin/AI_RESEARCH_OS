"""Human-readable citation references from saved canonical source fields."""

from __future__ import annotations

from typing import Any


def source_display(value: Any) -> str:
    if isinstance(value, dict):
        title = value.get("title")
        url = value.get("canonical_url")
        title = title.strip() if isinstance(title, str) else ""
        url = url.strip() if isinstance(url, str) else ""
        if title and url:
            return f"{title} — {url}"
        if title or url:
            return title or url
        return "Відомості про джерело недоступні"
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "Відомості про джерело недоступні"
