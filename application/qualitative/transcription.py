from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from domain.qualitative.authority import TranscriptSegment


@dataclass(frozen=True)
class ProviderTranscriptionResult:
    provider: str
    provider_job_id: str
    provider_config: str
    source_artifact_id: str
    segments: tuple[TranscriptSegment, ...]


class TranscriptionProvider(Protocol):
    def submit(self, *, artifact_id: str, content: bytes, media_type: str) -> str: ...
    def result(self, *, provider_job_id: str, source_artifact_id: str) -> ProviderTranscriptionResult: ...


class DeterministicTranscriptionProvider:
    """Provider-free acceptance adapter; fixtures are explicit and immutable."""
    external_participant_transfer = False
    def __init__(self, fixtures: dict[str, tuple[TranscriptSegment, ...]]):
        self._fixtures = dict(fixtures)

    def submit(self, *, artifact_id: str, content: bytes, media_type: str) -> str:
        if artifact_id not in self._fixtures:
            raise ValueError("No deterministic transcription fixture")
        return f"fixture:{artifact_id}"

    def result(self, *, provider_job_id: str, source_artifact_id: str) -> ProviderTranscriptionResult:
        if provider_job_id != f"fixture:{source_artifact_id}":
            raise ValueError("Provider result is bound to a different job or artifact")
        return ProviderTranscriptionResult("deterministic", provider_job_id, "fixture-v1",
                                           source_artifact_id, self._fixtures[source_artifact_id])
