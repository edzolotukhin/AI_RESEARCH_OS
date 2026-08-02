from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.source import Source
from domain.sources.source_candidate import SourceCandidate

from application.ports.source_ports import SourceRetriever
from infrastructure.retrieval.html_text_extractor import extract_text_from_html
from infrastructure.retrieval.network_safety import UnsafeUrlError
from infrastructure.retrieval.redirect_fetcher import fetch_with_validated_redirects


@dataclass(frozen=True)
class HttpRetrievalLimits:
    timeout_seconds: float = 10.0
    max_redirects: int = 5
    max_body_bytes: int = 512_000


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
    ) -> None:
        self._limits = limits or HttpRetrievalLimits()
        self._http_client = http_client

    def retrieve(self, candidate: SourceCandidate) -> Source:
        now = datetime.now(timezone.utc).isoformat()
        client = self._http_client or self._default_client()
        try:
            response = fetch_with_validated_redirects(
                client,
                candidate.url,
                max_redirects=self._limits.max_redirects,
                timeout=self._limits.timeout_seconds,
            )
        except UnsafeUrlError as exc:
            return self._failed_source(candidate, now, reason=str(exc))
        except Exception as exc:  # noqa: BLE001
            return self._failed_source(candidate, now, reason=str(exc))

        final_url = str(response.url)
        content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
        body = response.content[: self._limits.max_body_bytes]
        truncated = len(response.content) > self._limits.max_body_bytes

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
                    metadata={"reason": "PDF retrieval deferred in DR-03 v1"},
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
                metadata={"reason": f"Unsupported content type: {content_type}"},
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
            )

        status = RetrievalStatus.TRUNCATED if truncated else RetrievalStatus.ACQUIRED
        metadata: dict[str, object] = {}
        if truncated:
            metadata["truncated"] = True
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
            metadata=metadata,
        )

    def _failed_source(
        self,
        candidate: SourceCandidate,
        retrieved_at: str,
        *,
        reason: str,
        content_type: str = "",
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
            metadata={"reason": reason},
        )

    def _default_client(self):
        return httpx.Client(timeout=self._limits.timeout_seconds)
