from __future__ import annotations

import re


_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style)\b[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def extract_text_from_html(html: str) -> str:
    """Minimal HTML-to-text extraction without a browser engine."""
    without_blocks = _SCRIPT_STYLE_RE.sub(" ", html)
    without_tags = _TAG_RE.sub(" ", without_blocks)
    text = _WHITESPACE_RE.sub(" ", without_tags).strip()
    return text
