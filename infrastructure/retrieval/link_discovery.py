from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse


@dataclass(frozen=True)
class DiscoveredLink:
    url: str
    text: str
    resource_hint: str
    score: int


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str, dict[str, str]]] = []
        self._href: str | None = None
        self._attrs: dict[str, str] = {}
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.casefold() != "a":
            return
        attributes = {str(key).casefold(): str(value or "") for key, value in attrs}
        self._href = attributes.get("href")
        self._attrs = attributes
        self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag.casefold() == "a" and self._href:
            self.links.append((self._href, " ".join(self._text).strip(), self._attrs))
            self._href = None
            self._text = []


def discover_links(html: str, *, base_url: str, terms: tuple[str, ...] = ()) -> tuple[DiscoveredLink, ...]:
    parser = _LinkParser()
    parser.feed(html)
    result: list[DiscoveredLink] = []
    seen: set[str] = set()
    page_has_table_format = any(
        marker in html.casefold()
        for marker in (".xlsx", "xlsx", ".csv", "csv", "spreadsheet", "таблич")
    )
    for href, text, attrs in parser.links:
        url = urljoin(base_url, href).split("#", 1)[0]
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or url in seen:
            continue
        seen.add(url)
        haystack = f"{url} {text} {' '.join(attrs.values())}".casefold()
        score = sum(3 for term in terms if term.casefold() in haystack)
        path = parsed.path.casefold()
        hint = "html"
        download_hint = any(
            key in attrs for key in ("download", "data-download", "data-resource", "data-format", "type")
        ) or any(word in haystack for word in ("завантаж", "download", "file", "файл"))
        if (
            path.endswith((".xlsx", ".csv"))
            or "xlsx" in haystack
            or "csv" in haystack
            or (page_has_table_format and download_hint)
        ):
            hint = "table"
            score += 10
        elif path.endswith(".pdf") or "pdf" in haystack:
            hint = "pdf"
            score += 4
        elif any(word in haystack for word in ("resource", "download", "file", "data")):
            score += 2
        result.append(DiscoveredLink(url, text, hint, score))
    return tuple(sorted(result, key=lambda item: (-item.score, item.url)))
