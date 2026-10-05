from __future__ import annotations

import httpx

from application.qualitative.transcription import ProviderTranscriptionResult
from domain.qualitative.authority import SpeakerRole, TranscriptSegment, TranscriptWord


class AssemblyAITranscriptionProvider:
    """Narrow prerecorded adapter; credentials never enter canonical objects or errors."""
    external_participant_transfer = True
    def __init__(self, *, api_key: str, base_url: str = "https://api.assemblyai.com/v2", client=None):
        if not api_key:
            raise ValueError("AssemblyAI API key is required")
        self._headers = {"authorization": api_key}
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=30.0)

    def submit(self, *, artifact_id: str, content: bytes, media_type: str) -> str:
        uploaded = self._client.post(f"{self._base_url}/upload", headers=self._headers, content=content)
        uploaded.raise_for_status()
        upload_url = uploaded.json()["upload_url"]
        response = self._client.post(f"{self._base_url}/transcript", headers=self._headers,
                                     json={"audio_url": upload_url, "speaker_labels": True})
        response.raise_for_status()
        return str(response.json()["id"])

    def result(self, *, provider_job_id: str, source_artifact_id: str) -> ProviderTranscriptionResult:
        response = self._client.get(f"{self._base_url}/transcript/{provider_job_id}", headers=self._headers)
        response.raise_for_status()
        value = response.json()
        if value.get("status") != "completed":
            raise RuntimeError(f"Transcription is not complete: {value.get('status', 'unknown')}")
        segments = []
        for order, utterance in enumerate(value.get("utterances") or ()):
            words = tuple(TranscriptWord(str(word["text"]), int(word["start"]), int(word["end"]))
                          for word in utterance.get("words") or ())
            segments.append(TranscriptSegment(
                f"segment-{order + 1:04d}", order, str(utterance["text"]),
                speaker_label=str(utterance.get("speaker")) if utterance.get("speaker") is not None else None,
                speaker_role=SpeakerRole.UNKNOWN, start_ms=int(utterance["start"]),
                end_ms=int(utterance["end"]), words=words,
            ))
        if not segments:
            raise ValueError("Provider result contains no transcript segments")
        return ProviderTranscriptionResult("assemblyai", provider_job_id, "speaker_labels=true",
                                           source_artifact_id, tuple(segments))
