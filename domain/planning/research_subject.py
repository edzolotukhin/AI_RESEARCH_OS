from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any
from uuid import uuid4


VERSION = "RESEARCH_SUBJECT/1"
ALLOWED_RELATION_TYPES = frozenset({
    "population_context", "regulatory_context", "trade_import_context",
    "channel_context", "economic_context", "clinical_technical_context",
})


class SubjectResolutionStatus(str, Enum):
    RESOLVED = "resolved"
    PARTIALLY_RESOLVED = "partially_resolved"
    UNRESOLVED = "unresolved"


class RepresentationApprovalStatus(str, Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"


def normalize_subject_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(value.split())


_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)


def subject_tokens(value: str) -> frozenset[str]:
    return frozenset(
        token for token in _WORD_RE.findall(normalize_subject_text(value))
        if len(token) >= 2 and not token.isdigit()
    )


@dataclass(frozen=True)
class LexicalRepresentation:
    representation_id: str
    language: str
    label: str
    normalized_phrases: tuple[str, ...]
    concept_refs: tuple[str, ...]
    provenance: str
    approval_status: RepresentationApprovalStatus = RepresentationApprovalStatus.PROPOSED

    def __post_init__(self) -> None:
        object.__setattr__(self, "approval_status", RepresentationApprovalStatus(self.approval_status))
        phrases = tuple(dict.fromkeys(
            phrase for phrase in (normalize_subject_text(item) for item in self.normalized_phrases)
            if phrase
        ))
        label = str(self.label).strip()
        if not phrases and label:
            phrases = (normalize_subject_text(label),)
        object.__setattr__(self, "normalized_phrases", phrases)
        object.__setattr__(self, "concept_refs", tuple(dict.fromkeys(self.concept_refs)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "representation_id": self.representation_id,
            "language": self.language,
            "label": self.label,
            "normalized_phrases": list(self.normalized_phrases),
            "concept_refs": list(self.concept_refs),
            "provenance": self.provenance,
            "approval_status": self.approval_status.value,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "LexicalRepresentation":
        return cls(
            representation_id=str(value["representation_id"]),
            language=str(value.get("language") or "und"),
            label=str(value["label"]),
            normalized_phrases=tuple(str(x) for x in value.get("normalized_phrases", ())),
            concept_refs=tuple(str(x) for x in value.get("concept_refs", ())),
            provenance=str(value.get("provenance") or "unknown"),
            approval_status=RepresentationApprovalStatus(value.get("approval_status", "proposed")),
        )


@dataclass(frozen=True)
class SupportingRelation:
    relation_id: str
    relation_type: str
    information_need_refs: tuple[str, ...]
    concepts: tuple[str, ...]
    lexical_representations: tuple[LexicalRepresentation, ...]
    explanation: str

    def __post_init__(self) -> None:
        if self.relation_type not in ALLOWED_RELATION_TYPES:
            raise ValueError(f"Unsupported ResearchSubject relation type: {self.relation_type}")
        if not self.information_need_refs:
            raise ValueError("Supporting relation requires information_need_refs")

    def to_dict(self) -> dict[str, Any]:
        return {
            "relation_id": self.relation_id,
            "relation_type": self.relation_type,
            "information_need_refs": list(self.information_need_refs),
            "concepts": list(self.concepts),
            "lexical_representations": [x.to_dict() for x in self.lexical_representations],
            "explanation": self.explanation,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SupportingRelation":
        return cls(
            relation_id=str(value["relation_id"]),
            relation_type=str(value["relation_type"]),
            information_need_refs=tuple(str(x) for x in value.get("information_need_refs", ())),
            concepts=tuple(str(x) for x in value.get("concepts", ())),
            lexical_representations=tuple(
                LexicalRepresentation.from_dict(x)
                for x in value.get("lexical_representations", ())
            ),
            explanation=str(value.get("explanation") or ""),
        )


@dataclass(frozen=True)
class ResearchSubject:
    subject_id: str
    canonical_label: str
    canonical_language: str
    core_concepts: tuple[str, ...]
    lexical_representations: tuple[LexicalRepresentation, ...]
    supporting_relations: tuple[SupportingRelation, ...] = ()
    exclusions: tuple[str, ...] = ()
    resolution_status: SubjectResolutionStatus = SubjectResolutionStatus.UNRESOLVED
    provenance: dict[str, Any] | None = None
    version: str = VERSION
    semantic_fingerprint: str = ""

    def __post_init__(self) -> None:
        if self.version != VERSION:
            raise ValueError(f"Unsupported ResearchSubject version: {self.version}")
        object.__setattr__(self, "resolution_status", SubjectResolutionStatus(self.resolution_status))
        expected = self.compute_fingerprint()
        if self.semantic_fingerprint and self.semantic_fingerprint != expected:
            raise ValueError("ResearchSubject semantic fingerprint mismatch")
        object.__setattr__(self, "semantic_fingerprint", expected)

    @property
    def approved_representations(self) -> tuple[LexicalRepresentation, ...]:
        return tuple(
            item for item in self.lexical_representations
            if item.approval_status is RepresentationApprovalStatus.APPROVED
        )

    @property
    def executable(self) -> bool:
        return (
            self.resolution_status in {
                SubjectResolutionStatus.RESOLVED,
                SubjectResolutionStatus.PARTIALLY_RESOLVED,
            }
            and bool(self.canonical_label.strip())
            and bool(self.core_concepts)
            and bool(self.approved_representations)
        )

    def approve(self) -> "ResearchSubject":
        if self.resolution_status is SubjectResolutionStatus.UNRESOLVED:
            raise ValueError("Предмет дослідження не визначено; дизайн не можна затвердити")
        approved = tuple(
            replace(item, approval_status=RepresentationApprovalStatus.APPROVED)
            for item in self.lexical_representations
        )
        relations = tuple(
            replace(rel, lexical_representations=tuple(
                replace(item, approval_status=RepresentationApprovalStatus.APPROVED)
                for item in rel.lexical_representations
            ))
            for rel in self.supporting_relations
        )
        return replace(self, lexical_representations=approved, supporting_relations=relations,
                       semantic_fingerprint="")

    def semantic_payload(self) -> dict[str, Any]:
        def representation_payload(item: LexicalRepresentation) -> dict[str, Any]:
            return {
                "representation_id": item.representation_id,
                "language": normalize_subject_text(item.language),
                "label": normalize_subject_text(item.label),
                "normalized_phrases": sorted(item.normalized_phrases),
                "concept_refs": sorted(item.concept_refs),
                "approval_status": item.approval_status.value,
            }

        def relation_payload(item: SupportingRelation) -> dict[str, Any]:
            return {
                "relation_id": item.relation_id,
                "relation_type": item.relation_type,
                "information_need_refs": sorted(item.information_need_refs),
                "concepts": sorted(item.concepts),
                "lexical_representations": sorted(
                    (representation_payload(x) for x in item.lexical_representations),
                    key=lambda x: x["representation_id"],
                ),
                "explanation": normalize_subject_text(item.explanation),
            }
        return {
            "version": self.version,
            "subject_id": self.subject_id,
            "canonical_label": normalize_subject_text(self.canonical_label),
            "canonical_language": normalize_subject_text(self.canonical_language),
            "core_concepts": sorted(normalize_subject_text(x) for x in self.core_concepts),
            "lexical_representations": sorted(
                (representation_payload(x) for x in self.lexical_representations),
                key=lambda x: x["representation_id"],
            ),
            "supporting_relations": sorted(
                (relation_payload(x) for x in self.supporting_relations),
                key=lambda x: x["relation_id"],
            ),
            "exclusions": sorted(normalize_subject_text(x) for x in self.exclusions),
            "resolution_status": self.resolution_status.value,
        }

    def compute_fingerprint(self) -> str:
        encoded = json.dumps(self.semantic_payload(), ensure_ascii=False,
                             sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "subject_id": self.subject_id,
            "canonical_label": self.canonical_label,
            "canonical_language": self.canonical_language,
            "core_concepts": list(self.core_concepts),
            "lexical_representations": [x.to_dict() for x in self.lexical_representations],
            "supporting_relations": [x.to_dict() for x in self.supporting_relations],
            "exclusions": list(self.exclusions),
            "resolution_status": self.resolution_status.value,
            "semantic_fingerprint": self.semantic_fingerprint,
            "provenance": dict(self.provenance or {}),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "ResearchSubject | None":
        if value is None:
            return None
        return cls(
            version=str(value.get("version") or VERSION),
            subject_id=str(value["subject_id"]),
            canonical_label=str(value.get("canonical_label") or ""),
            canonical_language=str(value.get("canonical_language") or "und"),
            core_concepts=tuple(str(x) for x in value.get("core_concepts", ())),
            lexical_representations=tuple(
                LexicalRepresentation.from_dict(x)
                for x in value.get("lexical_representations", ())
            ),
            supporting_relations=tuple(
                SupportingRelation.from_dict(x)
                for x in value.get("supporting_relations", ())
            ),
            exclusions=tuple(str(x) for x in value.get("exclusions", ())),
            resolution_status=SubjectResolutionStatus(value.get("resolution_status", "unresolved")),
            provenance=dict(value.get("provenance") or {}),
            semantic_fingerprint=str(value.get("semantic_fingerprint") or ""),
        )

    @classmethod
    def proposed(cls, *, canonical_label: str, canonical_language: str,
                 aliases: tuple[tuple[str, str], ...] = (), provenance: str = "brief",
                 supporting_relations: tuple[SupportingRelation, ...] = (),
                 exclusions: tuple[str, ...] = ()) -> "ResearchSubject":
        label = str(canonical_label or "").strip()
        subject_id = str(uuid4())
        if not label:
            return cls(subject_id=subject_id, canonical_label="", canonical_language=canonical_language,
                       core_concepts=(), lexical_representations=(),
                       resolution_status=SubjectResolutionStatus.UNRESOLVED,
                       provenance={"resolver": provenance})
        concept = "core-subject"
        rows = ((canonical_language, label), *aliases)
        representations = tuple(
            LexicalRepresentation(
                representation_id=f"subject-representation-{index}", language=language,
                label=value, normalized_phrases=(value,), concept_refs=(concept,),
                provenance=provenance,
            )
            for index, (language, value) in enumerate(rows, start=1) if str(value).strip()
        )
        return cls(subject_id=subject_id, canonical_label=label,
                   canonical_language=canonical_language, core_concepts=(concept,),
                   lexical_representations=representations,
                   supporting_relations=supporting_relations,
                   exclusions=exclusions,
                   resolution_status=SubjectResolutionStatus.RESOLVED,
                   provenance={"resolver": provenance})
