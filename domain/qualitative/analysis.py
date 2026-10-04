"""Closed-world, immutable qualitative coding and thematic-analysis authority."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AnalyticalOrigin(str, Enum):
    HUMAN = "human"
    AI_PROPOSED = "ai_proposed"
    IMPORTED = "imported"


class ReviewState(str, Enum):
    DRAFT = "draft"
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


@dataclass(frozen=True)
class CorpusMember:
    session_id: str
    participant_id: str
    participant_pseudonym: str
    transcript_version_id: str
    transcript_checksum: str
    source_artifact_id: str
    consent_record_id: str


@dataclass(frozen=True)
class CodeDefinition:
    code_id: str
    label: str
    definition: str
    inclusion_criteria: str = ""
    exclusion_criteria: str = ""
    memo: str = ""
    origin: AnalyticalOrigin = AnalyticalOrigin.HUMAN

    def __post_init__(self):
        if not self.code_id or not self.label.strip() or not self.definition.strip():
            raise ValueError("Code identity, label and definition are required")


@dataclass(frozen=True)
class CodeApplication:
    application_id: str
    code_id: str
    transcript_version_id: str
    transcript_checksum: str
    segment_id: str
    start: int
    end: int
    session_id: str
    participant_id: str
    participant_pseudonym: str
    origin: AnalyticalOrigin
    review_state: ReviewState
    memo: str = ""

    def __post_init__(self):
        if self.start < 0 or self.end <= self.start:
            raise ValueError("Code application span is invalid")


def reject_population_claim(text: str) -> None:
    lowered = text.casefold()
    forbidden = ("% of customers", "% of consumers", "most consumers", "population prefers",
                 "% клієнтів", "більшість споживачів", "населення віддає перевагу")
    if any(value in lowered for value in forbidden):
        raise ValueError("Qualitative corpus coverage cannot be a population claim")
