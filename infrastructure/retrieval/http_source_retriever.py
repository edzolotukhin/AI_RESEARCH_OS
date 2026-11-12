from __future__ import annotations

import hashlib
from dataclasses import replace
from urllib.parse import urlsplit

import httpx

from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.source import Source
from domain.sources.source_candidate import SourceCandidate

from application.ports.source_ports import SourceRetriever
from infrastructure.retrieval.html_text_extractor import extract_text_from_html
from infrastructure.retrieval.network_safety import UnsafeUrlError
from infrastructure.retrieval.redirect_fetcher import fetch_with_validated_redirects
from infrastructure.retrieval.xlsx_text_extractor import (
    XLSX_CONTENT_TYPE,
    extract_xlsx_text,
    is_unsupported_spreadsheet_url,
    is_xlsx_content_type,
    looks_like_xlsx_url,
)
from infrastructure.retrieval.link_discovery import discover_links
from infrastructure.retrieval.navigation_budget import NavigationBudget, NavigationLimit
from application.sources.acquisition_capability import ACQUISITION_CAPABILITY, TEXT_EXTRACTION_CAPABILITY, TABLE_EXTRACTION_CAPABILITY


RETRIEVAL_FAILURE_CATEGORIES = {
    "dns_resolution_failed",
    "unsafe_address",
    "http_error",
    "timeout",
    "unsupported_content_type",
    "content_too_large",
    "other_retrieval_error",
}


class HttpRetrievalLimits:
    timeout_seconds: float = 10.0
    max_redirects: int = 5
    max_body_bytes: int = 512_000

    def __init__(
        self,
        *,
        timeout_seconds: float = 10.0,
        max_redirects: int = 5,
        max_body_bytes: int = 512_000,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_redirects = max_redirects
        self.max_body_bytes = max_body_bytes


class HttpSourceRetriever(SourceRetriever):
    """HTTP GET retriever with validated redirect chain and bounded payload."""

    _SUPPORTED_CONTENT_TYPES = (
        "text/html",
        "text/plain",
        "application/xhtml+xml",
    )

    def known_unsupported_url(self, url: str) -> bool:
        # PDF bodies are explicitly unsupported by this HTML/text/XLSX adapter.
        # Screen only an unambiguous path extension; redirects/content types
        # remain the responsibility of retrieve().
        return urlsplit(url).path.casefold().endswith(".pdf")

    def __init__(
        self,
        *,
        limits: HttpRetrievalLimits | None = None,
        http_client=None,
        dns_timeout_seconds: float = 5.0,
        xlsx_extraction_revision: str = TABLE_EXTRACTION_CAPABILITY,
    ) -> None:
        self._limits = limits or HttpRetrievalLimits()
        self._http_client = http_client
        self._dns_timeout_seconds = dns_timeout_seconds
        self.xlsx_extraction_revision = xlsx_extraction_revision

    def retrieve(self, candidate: SourceCandidate) -> Source:
        if self._http_client is None:
            with self._default_client() as client:
                return HttpSourceRetriever(limits=self._limits, http_client=client,
                    dns_timeout_seconds=self._dns_timeout_seconds,
                    xlsx_extraction_revision=self.xlsx_extraction_revision).retrieve(candidate)
        nav = _navigation_metadata(candidate)
        def limit(name, default, ceiling):
            try:
                return min(ceiling, max(1, int(candidate.metadata.get(name, default))))
            except (ValueError, TypeError):
                return default
        budget = NavigationBudget(max_requests=limit("navigation_max_requests", 12, 24),
            max_bytes=limit("navigation_max_bytes", 2_048_000, 8_192_000),
            max_links=limit("navigation_total_links", 25, 50))
        structured = candidate.metadata.get("required_resource_kind") == "table"
        def walk(current, depth, chain):
            metadata = dict(current.metadata)
            metadata["navigation_enabled"] = "0"
            source = self._retrieve_single(replace(current, metadata=metadata), budget)
            links = source.metadata.pop("_navigation_links", ())
            hops = source.metadata.pop("_http_chain", (current.url, source.url))
            path = list(chain)
            for hop in hops:
                if not path or path[-1] != hop:
                    path.append(hop)
            source.metadata["navigation_chain"] = path
            valid = source.retrieval_status in {RetrievalStatus.ACQUIRED, RetrievalStatus.TRUNCATED} and bool(source.content_text)
            table = bool(source.metadata.get("structured_rows"))
            html = source.content_type in {"text/html", "application/xhtml+xml"}
            challenge = any(s in source.content_text.casefold() for s in ("just a moment", "verify you are human", "access denied", "enable javascript and cookies"))
            if valid and (table or (not structured and not challenge and (not nav["enabled"] or not links))):
                budget.stop_reason = "selected_terminal_resource"
                return source
            if html and nav["enabled"] and depth < nav["max_depth"]:
                for link in links[:nav["max_links"]]:
                    if budget.considered_links >= budget.max_links:
                        budget.stop_reason = "link_budget_exhausted"
                        break
                    budget.considered_links += 1
                    from application.sources.url_canonicalizer import canonicalize_url
                    if canonicalize_url(link.url) in budget.visited:
                        budget.event(url=link.url, decision="rejected", reason="visited", score=link.score)
                        continue
                    if link.score <= 0:
                        budget.event(url=link.url, decision="rejected", reason="irrelevant", score=link.score)
                        continue
                    budget.event(url=link.url, decision="considered", reason=link.resource_hint, score=link.score)
                    result = walk(replace(current, url=link.url), depth+1, tuple(path))
                    if result.retrieval_status in {RetrievalStatus.ACQUIRED, RetrievalStatus.TRUNCATED} and result.content_text:
                        result.metadata["navigation_selected_link"] = {"url": result.url, "text": link.text[:100], "hint": link.resource_hint}
                        budget.event(url=link.url, decision="selected", score=link.score)
                        return result
                    budget.event(url=link.url, decision="rejected", reason=result.metadata.get("reason", "not_terminal"), score=link.score)
                    if budget.stop_reason in {"request_budget_exhausted", "byte_budget_exhausted", "link_budget_exhausted"}:
                        break
            if valid and not structured and not challenge:
                budget.stop_reason = "selected_terminal_resource"
                return source
            if valid:
                source.retrieval_status = RetrievalStatus.FAILED
                source.metadata["reason"] = "required_terminal_not_found" if structured else "html_challenge"
                # The table-required traversal is a distinct extraction contract
                # from a successful text-only snapshot of the same HTML bytes.
                source.extraction_revision = "navigation-table-unresolved-v2" if structured else "navigation-challenge-v2"
            if not budget.stop_reason:
                budget.stop_reason = "depth_limit" if depth >= nav["max_depth"] else "no_terminal_resource"
            return source
        source = walk(candidate, 0, ())
        diagnostics = budget.diagnostics()
        diagnostics.update({"considered": True, "activated": nav["enabled"],
            "max_depth": nav["max_depth"],
            "selected_link": source.url if source.retrieval_status in {RetrievalStatus.ACQUIRED, RetrievalStatus.TRUNCATED} else None,
            "final_url": source.url, "terminal_content_type": source.content_type})
        source.metadata["navigation_diagnostics"] = diagnostics
        source.metadata["acquisition_capability"] = ACQUISITION_CAPABILITY
        return source

    def _retrieve_single(self, candidate: SourceCandidate, budget) -> Source:
        now = _utc_now_iso()
        client = self._http_client or self._default_client()
        try:
            response = fetch_with_validated_redirects(
                client,
                candidate.url,
                max_redirects=self._limits.max_redirects,
                timeout=self._limits.timeout_seconds,
                dns_timeout_seconds=self._dns_timeout_seconds,
                navigation_budget=budget,
            )
        except NavigationLimit as exc:
            if str(exc) != "url_already_visited":
                budget.stop_reason = str(exc)
            return self._failed_source(candidate, now, reason=str(exc), category="content_too_large")
        except UnsafeUrlError as exc:
            return self._failed_source(
                candidate,
                now,
                reason=str(exc),
                category=exc.category,
            )
        except httpx.TimeoutException as exc:
            return self._failed_source(
                candidate,
                now,
                reason=str(exc) or "Request timed out",
                category="timeout",
            )
        except httpx.HTTPStatusError as exc:
            return self._failed_source(
                candidate,
                now,
                reason=str(exc),
                category="http_error",
            )
        except Exception as exc:  # noqa: BLE001
            return self._failed_source(
                candidate,
                now,
                reason=str(exc),
                category="other_retrieval_error",
            )

        final_url = str(response.url)
        content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
        body = response.content[: self._limits.max_body_bytes]
        truncated = len(response.content) > self._limits.max_body_bytes

        if response.status_code >= 400:
            return self._failed_source(
                candidate,
                now,
                reason=f"HTTP {response.status_code} for {final_url}",
                category="http_error",
                content_type=content_type,
            )

        navigation = _navigation_metadata(candidate)
        navigation_diagnostics = dict(candidate.metadata.get("navigation_diagnostics") or {})
        navigation_diagnostics.update({
            "considered": True,
            "activated": bool(
                content_type.startswith("text/html")
                and navigation["enabled"]
                and navigation["depth"] < navigation["max_depth"]
            ),
        })
        if self._should_extract_xlsx(content_type=content_type, url=final_url, body=body):
            terminal = self._acquire_xlsx(
                candidate=candidate,
                retrieved_at=now,
                final_url=final_url,
                content_type=content_type or XLSX_CONTENT_TYPE,
                body=body,
                body_truncated=truncated,
            )
            if navigation_diagnostics.get("considered"):
                terminal.metadata["navigation_diagnostics"] = navigation_diagnostics
            terminal.raw_content_checksum = hashlib.sha256(body).hexdigest()
            terminal.raw_checksum_kind = "sha256-bytes" if not truncated else "legacy-surrogate"
            terminal.extraction_revision = self.xlsx_extraction_revision
            if isinstance(response, httpx.Response):
                terminal.metadata["_http_chain"] = response.extensions.get("validated_redirect_chain", (candidate.url, final_url))
            return terminal

        if is_unsupported_spreadsheet_url(final_url) or content_type in {
            "application/vnd.ms-excel",
            "application/vnd.ms-excel.sheet.binary.macroenabled.12",
            "application/vnd.oasis.opendocument.spreadsheet",
        }:
            return Source(
                id="",
                project_id="",
                url=final_url,
                canonical_url=final_url,
                title=candidate.title,
                retrieved_at=now,
                source_type=candidate.source_type or "web",
                content_type=content_type,
                retrieval_status=RetrievalStatus.UNSUPPORTED,
                metadata={
                    "reason": "unsupported_spreadsheet_format",
                    "failure_category": "unsupported_content_type",
                },
            )

        if not any(content_type.startswith(item) for item in self._SUPPORTED_CONTENT_TYPES):
            if content_type.startswith("application/pdf"):
                return Source(
                    id="",
                    project_id="",
                    url=final_url,
                    canonical_url=final_url,
                    title=candidate.title,
                    retrieved_at=now,
                    source_type=candidate.source_type or "web",
                    content_type=content_type,
                    retrieval_status=RetrievalStatus.UNSUPPORTED,
                    metadata={
                        "reason": "PDF retrieval deferred in DR-03 v1",
                        "failure_category": "unsupported_content_type",
                    },
                )
            return Source(
                id="",
                project_id="",
                url=final_url,
                canonical_url=final_url,
                title=candidate.title,
                retrieved_at=now,
                source_type=candidate.source_type or "web",
                content_type=content_type,
                retrieval_status=RetrievalStatus.UNSUPPORTED,
                metadata={
                    "reason": f"Unsupported content type: {content_type}",
                    "failure_category": "unsupported_content_type",
                },
            )

        text = body.decode("utf-8", errors="replace")
        if "html" in content_type:
            extracted = extract_text_from_html(text)
        else:
            extracted = text.strip()

        if not extracted:
            return self._failed_source(
                candidate,
                now,
                reason="No extractable text content",
                content_type=content_type,
                category="other_retrieval_error",
            )

        status = RetrievalStatus.TRUNCATED if truncated else RetrievalStatus.ACQUIRED
        metadata: dict[str, object] = {}
        if "html" in content_type:
            metadata["_navigation_links"] = discover_links(text, base_url=final_url,
                terms=tuple(filter(None, str(candidate.metadata.get("navigation_terms", "")).split("|"))))
        if isinstance(response, httpx.Response):
            metadata["_http_chain"] = response.extensions.get("validated_redirect_chain", (candidate.url, final_url))
        if navigation_diagnostics.get("considered"):
            metadata["navigation_diagnostics"] = navigation_diagnostics
        if truncated:
            metadata["truncated"] = True
            metadata["failure_category"] = "content_too_large"
        checksum = _content_checksum(extracted)
        return Source(
            id="",
            project_id="",
            url=final_url,
            canonical_url=final_url,
            title=candidate.title,
            retrieved_at=now,
            source_type=candidate.source_type or "web",
            content_type=content_type,
            retrieval_status=status,
            content_text=extracted,
            content_checksum=checksum,
            metadata=metadata,
            raw_content_checksum=hashlib.sha256(body).hexdigest(),
            raw_checksum_kind="sha256-bytes" if not truncated else "legacy-surrogate",
            extraction_revision=TEXT_EXTRACTION_CAPABILITY,
        )

    def _should_extract_xlsx(self, *, content_type: str, url: str, body: bytes = b"") -> bool:
        if is_xlsx_content_type(content_type):
            return True
        # Defensive fallback: .xlsx URL with ambiguous/octet-stream MIME.
        if looks_like_xlsx_url(url) and (
            not content_type
            or content_type
            in {
                "application/octet-stream",
                "binary/octet-stream",
                "application/zip",
            }
            or is_xlsx_content_type(content_type)
        ):
            return True
        if body[:2] == b"PK" and content_type in {
            "application/octet-stream", "binary/octet-stream", "application/zip", ""
        }:
            return True
        return False

    def _acquire_xlsx(
        self,
        *,
        candidate: SourceCandidate,
        retrieved_at: str,
        final_url: str,
        content_type: str,
        body: bytes,
        body_truncated: bool,
    ) -> Source:
        result = extract_xlsx_text(body, content_type=content_type)
        metadata: dict[str, object] = dict(result.metadata)
        if body_truncated:
            metadata["truncated"] = True
            metadata["body_truncated"] = True
            metadata["failure_category"] = "content_too_large"
            metadata["workbook_truncated"] = True

        if result.error == "encrypted_workbook":
            return Source(
                id="",
                project_id="",
                url=final_url,
                canonical_url=final_url,
                title=candidate.title,
                retrieved_at=retrieved_at,
                source_type=candidate.source_type or "web",
                content_type=content_type,
                retrieval_status=RetrievalStatus.UNSUPPORTED,
                metadata={
                    **metadata,
                    "reason": "encrypted_workbook",
                    "failure_category": "unsupported_content_type",
                },
            )

        if result.error in {"workbook_parse_failed", "no_renderable_cells"}:
            return Source(
                id="",
                project_id="",
                url=final_url,
                canonical_url=final_url,
                title=candidate.title,
                retrieved_at=retrieved_at,
                source_type=candidate.source_type or "web",
                content_type=content_type,
                retrieval_status=RetrievalStatus.FAILED,
                metadata={
                    **metadata,
                    "reason": result.error,
                    "failure_category": "other_retrieval_error",
                },
            )

        if result.error:
            return Source(
                id="",
                project_id="",
                url=final_url,
                canonical_url=final_url,
                title=candidate.title,
                retrieved_at=retrieved_at,
                source_type=candidate.source_type or "web",
                content_type=content_type,
                retrieval_status=RetrievalStatus.FAILED,
                metadata={
                    **metadata,
                    "reason": result.error,
                    "failure_category": "other_retrieval_error",
                },
            )

        text = result.text.strip()
        if not text:
            return Source(
                id="",
                project_id="",
                url=final_url,
                canonical_url=final_url,
                title=candidate.title,
                retrieved_at=retrieved_at,
                source_type=candidate.source_type or "web",
                content_type=content_type,
                retrieval_status=RetrievalStatus.FAILED,
                metadata={
                    **metadata,
                    "reason": "no_renderable_cells",
                    "failure_category": "other_retrieval_error",
                },
            )

        workbook_truncated = bool(metadata.get("workbook_truncated")) or body_truncated
        status = (
            RetrievalStatus.TRUNCATED
            if workbook_truncated or body_truncated
            else RetrievalStatus.ACQUIRED
        )
        if workbook_truncated:
            metadata["workbook_truncated"] = True
            metadata.setdefault("failure_category", "content_too_large")

        checksum = _content_checksum(text)
        return Source(
            id="",
            project_id="",
            url=final_url,
            canonical_url=final_url,
            title=candidate.title,
            retrieved_at=retrieved_at,
            source_type=candidate.source_type or "web",
            content_type=content_type,
            retrieval_status=status,
            content_text=text,
            content_checksum=checksum,
            metadata=metadata,
        )

    def _failed_source(
        self,
        candidate: SourceCandidate,
        retrieved_at: str,
        *,
        reason: str,
        content_type: str = "",
        category: str = "other_retrieval_error",
    ) -> Source:
        return Source(
            id="",
            project_id="",
            url=candidate.url,
            canonical_url=candidate.url,
            title=candidate.title,
            retrieved_at=retrieved_at,
            source_type=candidate.source_type or "web",
            content_type=content_type,
            retrieval_status=RetrievalStatus.FAILED,
            metadata={
                "reason": reason,
                "failure_category": category,
            },
        )

    def _default_client(self):
        return httpx.Client(timeout=self._limits.timeout_seconds)


def _utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _content_checksum(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _navigation_metadata(candidate: SourceCandidate) -> dict[str, object]:
    metadata = candidate.metadata or {}
    enabled = str(metadata.get("navigation_enabled", "0")).casefold() in {"1", "true", "yes"}
    def integer(name: str, default: int) -> int:
        try:
            return max(0, int(metadata.get(name, default)))
        except (TypeError, ValueError):
            return default
    return {
        "enabled": enabled,
        "depth": integer("navigation_depth", 0),
        "max_depth": min(3, integer("navigation_max_depth", 3)),
        "max_links": min(10, integer("navigation_max_links", 5)),
        "terms": tuple(item for item in str(metadata.get("navigation_terms", "")).split("|") if item),
        "visited": tuple(item for item in str(metadata.get("navigation_visited", "")).split("|") if item),
    }
