from __future__ import annotations

import hashlib

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

    def __init__(
        self,
        *,
        limits: HttpRetrievalLimits | None = None,
        http_client=None,
        dns_timeout_seconds: float = 5.0,
    ) -> None:
        self._limits = limits or HttpRetrievalLimits()
        self._http_client = http_client
        self._dns_timeout_seconds = dns_timeout_seconds

    def retrieve(self, candidate: SourceCandidate) -> Source:
        now = _utc_now_iso()
        client = self._http_client or self._default_client()
        try:
            response = fetch_with_validated_redirects(
                client,
                candidate.url,
                max_redirects=self._limits.max_redirects,
                timeout=self._limits.timeout_seconds,
                dns_timeout_seconds=self._dns_timeout_seconds,
            )
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

        if self._should_extract_xlsx(content_type=content_type, url=final_url):
            return self._acquire_xlsx(
                candidate=candidate,
                retrieved_at=now,
                final_url=final_url,
                content_type=content_type or XLSX_CONTENT_TYPE,
                body=body,
                body_truncated=truncated,
            )

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
        )

    def _should_extract_xlsx(self, *, content_type: str, url: str) -> bool:
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
