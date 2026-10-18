from __future__ import annotations

from dataclasses import dataclass
from typing import Any


CONTRACT_VERSION = "desk_evidence_candidate_v2"
VALIDATION_VERSION = "desk_semantic_assignment_v1"
MAX_REQUIRED_ASPECT_REFS = 8
MAX_SEMANTIC_JUSTIFICATION_CHARS = 500


@dataclass(frozen=True)
class ValidatedSemanticAssignment:
    subject_id: str
    subject_fingerprint: str
    binding_type: str
    supporting_relation_id: str | None
    information_need_id: str
    required_aspect_refs: tuple[str, ...]
    geography_applicability: tuple[str, ...]
    semantic_justification: str
    lexical_diagnostics: dict[str, Any]

    def to_metadata(self) -> dict[str, Any]:
        return {
            "contract_version": CONTRACT_VERSION,
            "subject_id": self.subject_id,
            "subject_fingerprint": self.subject_fingerprint,
            "binding_type": self.binding_type,
            "supporting_relation_id": self.supporting_relation_id,
            "information_need_id": self.information_need_id,
            "required_aspect_refs": list(self.required_aspect_refs),
            "geography_applicability": list(self.geography_applicability),
            "semantic_justification": self.semantic_justification,
            "validation_version": VALIDATION_VERSION,
            "lexical_diagnostics": dict(self.lexical_diagnostics),
        }


def semantic_assignment(metadata_or_evidence: Any) -> dict[str, Any] | None:
    metadata = getattr(metadata_or_evidence, "metadata", metadata_or_evidence)
    if not isinstance(metadata, dict):
        return None
    value = metadata.get("semantic_assignment")
    if (
        not isinstance(value, dict)
        or value.get("contract_version") != CONTRACT_VERSION
        or value.get("validation_version") != VALIDATION_VERSION
    ):
        return None
    return dict(value)


def required_aspect_refs(metadata_or_evidence: Any) -> tuple[str, ...]:
    assignment = semantic_assignment(metadata_or_evidence)
    if assignment is None:
        return ()
    refs = assignment.get("required_aspect_refs")
    if not isinstance(refs, list):
        return ()
    return tuple(str(item) for item in refs if isinstance(item, str) and item)
