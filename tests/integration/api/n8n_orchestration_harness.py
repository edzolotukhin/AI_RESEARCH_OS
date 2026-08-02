"""Shared n8n product-acceptance orchestration helpers."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Callable
from uuid import uuid4

from application.report.deduplication import compute_content_checksum
from tests.fixtures.research_brief import CANONICAL_BRIEF_REQUEST

N8N_ACCEPTANCE_BRIEF = dict(CANONICAL_BRIEF_REQUEST)
N8N_POLL_INTERVAL_SECONDS = 0.05
N8N_MAX_POLL_ATTEMPTS = 200
N8N_HTTP_MAX_RETRIES = 3
N8N_HTTP_RETRY_STATUS_CODES = {502, 503, 504}


@dataclass(frozen=True)
class N8nSuccessPayload:
    project_id: str
    run_id: str
    status: str
    review_verdict: str
    artifact_id: str
    artifact_filename: str
    artifact_media_type: str
    artifact_checksum: str
    artifact_content: str
    correlation_id: str
    idempotency_key: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "run_id": self.run_id,
            "status": self.status,
            "review_verdict": self.review_verdict,
            "artifact_id": self.artifact_id,
            "artifact_filename": self.artifact_filename,
            "artifact_media_type": self.artifact_media_type,
            "artifact_checksum": self.artifact_checksum,
            "artifact_content": self.artifact_content,
            "correlation_id": self.correlation_id,
            "idempotency_key": self.idempotency_key,
        }


class N8nOrchestrationHarness:
    """API-level harness mirroring the canonical n8n product-acceptance workflow."""

    def __init__(self, client, *, auth_headers: dict[str, str], worker_drain) -> None:
        self._client = client
        self._auth_headers = auth_headers
        self._worker_drain = worker_drain

    def create_project(self, *, name: str = "n8n Product Acceptance") -> str:
        response = self._request_with_retry(
            "POST",
            "/projects",
            json={"name": name},
        )
        if response.status_code != 201:
            raise AssertionError(
                f"Create project failed: {response.status_code} {response.text}",
            )
        return response.json()["id"]

    def submit_research(
        self,
        project_id: str,
        *,
        idempotency_key: str,
        correlation_id: str,
        brief: dict | None = None,
    ):
        body = {
            "brief": brief or N8N_ACCEPTANCE_BRIEF,
            "source": "n8n",
            "correlation_id": correlation_id,
        }
        return self._request_with_retry(
            "POST",
            f"/projects/{project_id}/research",
            json=body,
            headers={
                "Idempotency-Key": idempotency_key,
                "X-Correlation-ID": correlation_id,
                **self._auth_headers,
            },
        )

    def poll_until_terminal(
        self,
        run_id: str,
        *,
        max_attempts: int = N8N_MAX_POLL_ATTEMPTS,
        interval_seconds: float = N8N_POLL_INTERVAL_SECONDS,
    ) -> dict[str, Any]:
        for _ in range(max_attempts):
            response = self._client.get(
                f"/workflow-runs/{run_id}",
                headers=self._auth_headers,
            )
            if response.status_code != 200:
                raise AssertionError(
                    f"Poll failed: {response.status_code} {response.text}",
                )
            payload = response.json()
            if payload.get("is_terminal"):
                return payload
            time.sleep(interval_seconds)
        raise AssertionError(f"Run {run_id} did not reach terminal state")

    def drain_workers(self, container) -> None:
        self._worker_drain(container)

    def assert_approved_finality(self, terminal: dict[str, Any]) -> None:
        if terminal.get("status") != "completed":
            raise AssertionError(
                f"Expected completed, got {terminal.get('status')}: {terminal}",
            )
        if terminal.get("final_review_verdict") != "approve":
            raise AssertionError(
                f"Expected approve verdict, got {terminal.get('final_review_verdict')}",
            )
        if not terminal.get("final_artifact_available"):
            raise AssertionError("Expected final_artifact_available=true")
        if not terminal.get("final_artifact_id"):
            raise AssertionError("Expected final_artifact_id")

    def fetch_approved_artifact(self, artifact_id: str) -> dict[str, Any]:
        metadata = self._client.get(
            f"/artifacts/{artifact_id}",
            headers=self._auth_headers,
        )
        if metadata.status_code != 200:
            raise AssertionError(
                f"Artifact metadata failed: {metadata.status_code} {metadata.text}",
            )
        meta = metadata.json()
        if meta.get("artifact_type") != "research_report":
            raise AssertionError(f"Unexpected artifact_type: {meta.get('artifact_type')}")
        if meta.get("status") != "approved":
            raise AssertionError(f"Expected approved artifact, got {meta.get('status')}")
        if meta.get("media_type") != "text/markdown":
            raise AssertionError(f"Unexpected media_type: {meta.get('media_type')}")

        content_response = self._client.get(
            f"/artifacts/{artifact_id}/content",
            headers=self._auth_headers,
        )
        if content_response.status_code != 200:
            raise AssertionError(
                f"Artifact content failed: {content_response.status_code}",
            )
        content_payload = content_response.json()
        body = content_payload.get("content", "")
        if not body.strip():
            raise AssertionError("Artifact content is empty")
        if "agency/projects" in body or "\\\\" in body:
            raise AssertionError("Artifact content exposes internal filesystem paths")

        checksum = content_payload.get("content_checksum") or meta.get("content_checksum")
        actual = compute_content_checksum(body)
        if checksum and checksum != actual:
            raise AssertionError(
                f"Checksum mismatch: metadata={checksum} actual={actual}",
            )
        return {
            "metadata": meta,
            "content": content_payload,
            "checksum": checksum or actual,
        }

    def run_acceptance_flow(
        self,
        container,
        *,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
        project_name: str = "n8n Product Acceptance",
        drain: bool = True,
    ) -> N8nSuccessPayload:
        idempotency_key = idempotency_key or f"n8n-accept-{uuid4()}"
        correlation_id = correlation_id or f"corr-{uuid4()}"
        project_id = self.create_project(name=project_name)
        submit = self.submit_research(
            project_id,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )
        if submit.status_code != 202:
            raise AssertionError(
                f"Submit failed: {submit.status_code} {submit.text}",
            )
        run_id = submit.json()["run_id"]
        if drain:
            self.drain_workers(container)
        terminal = self.poll_until_terminal(run_id)
        self.assert_approved_finality(terminal)
        artifact_id = terminal["final_artifact_id"]
        artifact = self.fetch_approved_artifact(artifact_id)
        return N8nSuccessPayload(
            project_id=project_id,
            run_id=run_id,
            status=terminal["status"],
            review_verdict=terminal["final_review_verdict"],
            artifact_id=artifact_id,
            artifact_filename=artifact["metadata"]["filename"],
            artifact_media_type=artifact["metadata"]["media_type"],
            artifact_checksum=artifact["checksum"],
            artifact_content=artifact["content"]["content"],
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )

    def _request_with_retry(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        headers: dict | None = None,
        transport: Callable | None = None,
    ):
        merged_headers = dict(self._auth_headers)
        if headers:
            merged_headers.update(headers)
        last_response = None
        for attempt in range(N8N_HTTP_MAX_RETRIES):
            if transport is not None:
                response = transport(method, path, json=json, headers=merged_headers)
            elif method == "POST":
                response = self._client.post(path, json=json, headers=merged_headers)
            else:
                response = self._client.get(path, headers=merged_headers)
            last_response = response
            if response.status_code not in N8N_HTTP_RETRY_STATUS_CODES:
                return response
            if attempt + 1 >= N8N_HTTP_MAX_RETRIES:
                return response
            time.sleep(0.01 * (attempt + 1))
        assert last_response is not None
        return last_response


def research_body_fingerprint(project_id: str, brief: dict) -> str:
    canonical = json.dumps(
        {"project_id": project_id, "brief": brief},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
