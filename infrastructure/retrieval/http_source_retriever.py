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
