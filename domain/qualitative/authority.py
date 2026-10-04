from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from hashlib import sha256


class ConsentState(str, Enum):
    UNKNOWN = "unknown"
    ELIGIBLE = "eligible"
    WITHDRAWN = "withdrawn"


class ArtifactKind(str, Enum):
    AUDIO = "audio"
    PREPARED_DOCX = "prepared_docx"
    PREPARED_TEXT = "prepared_text"


class SourceMode(str, Enum):
    AUDIO_TRANSCRIPTION = "audio_transcription"
    PREPARED_TRANSCRIPT = "prepared_transcript"


class TranscriptKind(str, Enum):
    VERBATIM = "verbatim"
    CLEAN = "clean"


class SpeakerRole(str, Enum):
    PARTICIPANT = "participant"
    INTERVIEWER = "interviewer"
    OTHER = "other"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Participant:
    participant_id: str
    project_id: str
    run_id: str
    pseudonym: str
    attributes: tuple[tuple[str, str], ...] = ()

    def __post_init__(self):
        if not self.pseudonym.strip():
            raise ValueError("Participant pseudonym is required")


@dataclass(frozen=True)
class ConsentRecord:
    consent_id: str
    participant_id: str
    state: ConsentState
    recorded_at: datetime
    context: str
    researcher_attested: bool = False


@dataclass(frozen=True)
class Session:
    session_id: str
    project_id: str
    run_id: str
    participant_id: str
    method_id: str = "QUALITATIVE"
    method_version: str = "1"
    context: str = ""


@dataclass(frozen=True)
class QualitativeArtifact:
    artifact_id: str
    project_id: str
    run_id: str
    session_id: str
    kind: ArtifactKind
    checksum: str
    byte_size: int
    media_type: str
    original_filename: str
    imported_at: datetime

    @classmethod
    def from_bytes(cls, *, content: bytes, **values):
        return cls(checksum=sha256(content).hexdigest(), byte_size=len(content), **values)

    def verify(self, content: bytes) -> None:
        if len(content) != self.byte_size or sha256(content).hexdigest() != self.checksum:
            raise ValueError("Immutable qualitative artifact bytes changed")


@dataclass(frozen=True)
class TranscriptWord:
    text: str
    start_ms: int | None = None
    end_ms: int | None = None

    def __post_init__(self):
        if (self.start_ms is None) != (self.end_ms is None):
            raise ValueError("Word timing must be complete or absent")
        if self.start_ms is not None and not 0 <= self.start_ms <= self.end_ms:
            raise ValueError("Invalid word timing")


@dataclass(frozen=True)
class TranscriptSegment:
    segment_id: str
    order: int
    text: str
    speaker_label: str | None = None
    speaker_role: SpeakerRole = SpeakerRole.UNKNOWN
    start_ms: int | None = None
    end_ms: int | None = None
    words: tuple[TranscriptWord, ...] = ()

    def __post_init__(self):
        if not self.text or self.order < 0:
            raise ValueError("Transcript segment text and order are required")
        if (self.start_ms is None) != (self.end_ms is None):
            raise ValueError("Segment timing must be complete or absent")
        if self.start_ms is not None and not 0 <= self.start_ms <= self.end_ms:
            raise ValueError("Invalid segment timing")


@dataclass(frozen=True)
class TranscriptVersion:
    transcript_version_id: str
    project_id: str
    run_id: str
    session_id: str
    source_artifact_id: str
    source_mode: SourceMode
    version: int
    kind: TranscriptKind
    segments: tuple[TranscriptSegment, ...]
    checksum: str
    parent_version_id: str | None = None
    language: str | None = None
    redacted: bool = False
    analysis_eligible: bool = False
    warnings: tuple[str, ...] = ()

    @classmethod
    def create(cls, **values):
        segments = tuple(values.pop("segments"))
        canonical = "\n".join(f"{x.order}\0{x.segment_id}\0{x.speaker_role.value}\0{x.text}\0{x.start_ms}\0{x.end_ms}" for x in segments)
        return cls(segments=segments, checksum=sha256(canonical.encode("utf-8")).hexdigest(), **values)

    def __post_init__(self):
        if not self.segments or tuple(x.order for x in self.segments) != tuple(range(len(self.segments))):
            raise ValueError("Transcript segments require stable contiguous order")
        if len({x.segment_id for x in self.segments}) != len(self.segments):
            raise ValueError("Duplicate transcript segment identity")
        if self.version > 1 and not self.parent_version_id:
            raise ValueError("Derived transcript version requires an exact parent")


@dataclass(frozen=True)
class TranscriptSpanRef:
    transcript_version_id: str
    transcript_checksum: str
    segment_id: str
    start: int
    end: int

    def resolve(self, transcript: TranscriptVersion) -> str:
        if transcript.transcript_version_id != self.transcript_version_id or transcript.checksum != self.transcript_checksum:
            raise ValueError("Stale or foreign transcript reference")
        segment = next((item for item in transcript.segments if item.segment_id == self.segment_id), None)
        if segment is None or not 0 <= self.start < self.end <= len(segment.text):
            raise ValueError("Invalid transcript span")
        return segment.text[self.start:self.end]


class QualitativeReadiness(str, Enum):
    PARTICIPANT_MISSING = "participant_missing"
    CONSENT_NOT_ELIGIBLE = "consent_not_eligible"
    SESSION_MISSING = "session_missing"
    SOURCE_MISSING = "source_missing"
    PROCESSING = "processing"
    TRANSCRIPT_WARNING = "transcript_warning"
    TRANSCRIPT_READY = "transcript_ready"
    AUTHORITY_READY_FOR_CODING = "authority_ready_for_coding"


def assess_readiness(*, participant, consent, session, artifact, transcript) -> QualitativeReadiness:
    if participant is None:
        return QualitativeReadiness.PARTICIPANT_MISSING
    if consent is None or consent.state is not ConsentState.ELIGIBLE:
        return QualitativeReadiness.CONSENT_NOT_ELIGIBLE
    if session is None:
        return QualitativeReadiness.SESSION_MISSING
    if artifact is None:
        return QualitativeReadiness.SOURCE_MISSING
    if transcript is None:
        return QualitativeReadiness.PROCESSING
    if transcript.warnings:
        return QualitativeReadiness.TRANSCRIPT_WARNING
    return (QualitativeReadiness.AUTHORITY_READY_FOR_CODING if transcript.analysis_eligible
            else QualitativeReadiness.TRANSCRIPT_READY)
