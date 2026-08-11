"""P1-09.1 Analysis-local Finding ↔ Evidence entailment contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

from domain.evidence.evidence import Evidence
from domain.planning.research_design import ResearchQuestion

from application.analysis.exceptions import FindingEntailmentError
from application.ports.analysis_ports import FindingCandidate


class FindingEntailmentStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    PARTIAL = "PARTIAL"
    UNSUPPORTED = "UNSUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


# Deterministic payload bounds (Analysis-local; do not raise stage budgets).
MAX_FINDING_STATEMENT_CHARS = 2000
MAX_FINDING_RATIONALE_CHARS = 2000
MAX_EVIDENCE_STATEMENT_CHARS = 2000
MAX_EVIDENCE_EXCERPT_CHARS = 2000
MAX_RQ_TEXT_CHARS = 500
MAX_CANDIDATES_PER_ENTAILMENT_BATCH = 20
MAX_CHARS_PER_ENTAILMENT_BATCH = 12000

_TRUNCATION_MARKER = "...[truncated]"


def _bound_text(value: str, *, limit: int) -> tuple[str, bool]:
    text = value if isinstance(value, str) else str(value or "")
    if len(text) <= limit:
        return text, False
    keep = max(0, limit - len(_TRUNCATION_MARKER))
    return text[:keep] + _TRUNCATION_MARKER, True


@dataclass(frozen=True)
class EntailmentEvidenceProjection:
    id: str
    statement: str
    source_excerpt: str
    truncated: bool = False

    def char_count(self) -> int:
        return len(self.id) + len(self.statement) + len(self.source_excerpt)


@dataclass(frozen=True)
class EntailmentCandidateProjection:
    candidate_id: str
    statement: str
    rationale: str
    evidence_refs: tuple[str, ...]
    research_question_text: str | None
    evidence: tuple[EntailmentEvidenceProjection, ...]
    truncated: bool = False

    def char_count(self) -> int:
        total = (
            len(self.candidate_id)
            + len(self.statement)
            + len(self.rationale)
            + sum(len(ref) for ref in self.evidence_refs)
            + (len(self.research_question_text or ""))
        )
        total += sum(item.char_count() for item in self.evidence)
        return total


@dataclass(frozen=True)
class FindingEntailmentVerdict:
    candidate_id: str
    status: FindingEntailmentStatus
    supported_evidence_ids: tuple[str, ...]
    unsupported_claim_parts: tuple[str, ...]
    rationale: str


@dataclass
class FindingEntailmentDiagnostics:
    generated_candidate_count: int = 0
    provenance_valid_candidate_count: int = 0
    entailment_submitted_count: int = 0
    entailment_accepted_count: int = 0
    entailment_calls: int = 0
    rejected_by_status: dict[str, int] = field(default_factory=dict)
    rejected_candidate_ids: list[str] = field(default_factory=list)
    budget_stop_reason: str | None = None

    def record_rejection(self, candidate_id: str, status: FindingEntailmentStatus) -> None:
        key = status.value
        self.rejected_by_status[key] = self.rejected_by_status.get(key, 0) + 1
        self.rejected_candidate_ids.append(candidate_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_candidate_count": self.generated_candidate_count,
            "provenance_valid_candidate_count": self.provenance_valid_candidate_count,
            "entailment_submitted_count": self.entailment_submitted_count,
            "entailment_accepted_count": self.entailment_accepted_count,
            "entailment_calls": self.entailment_calls,
            "rejected_by_status": dict(self.rejected_by_status),
            "rejected_candidate_ids": list(self.rejected_candidate_ids),
            "budget_stop_reason": self.budget_stop_reason,
        }


@dataclass(frozen=True)
class ProvenanceValidFinding:
    candidate_id: str
    candidate: FindingCandidate
    research_question_text: str | None = None


def project_entailment_candidate(
    item: ProvenanceValidFinding,
    *,
    evidence_by_id: dict[str, Evidence],
) -> EntailmentCandidateProjection:
    statement, stmt_truncated = _bound_text(
        item.candidate.statement,
        limit=MAX_FINDING_STATEMENT_CHARS,
    )
    rationale, rat_truncated = _bound_text(
        item.candidate.rationale,
        limit=MAX_FINDING_RATIONALE_CHARS,
    )
    rq_text = None
    rq_truncated = False
    if item.research_question_text:
        rq_text, rq_truncated = _bound_text(
            item.research_question_text,
            limit=MAX_RQ_TEXT_CHARS,
        )

    evidence_projections: list[EntailmentEvidenceProjection] = []
    any_ev_truncated = False
    for evidence_id in item.candidate.evidence_refs:
        evidence = evidence_by_id[evidence_id]
        ev_statement, ev_stmt_trunc = _bound_text(
            evidence.statement,
            limit=MAX_EVIDENCE_STATEMENT_CHARS,
        )
        ev_excerpt, ev_ex_trunc = _bound_text(
            evidence.source_excerpt or "",
            limit=MAX_EVIDENCE_EXCERPT_CHARS,
        )
        truncated = ev_stmt_trunc or ev_ex_trunc
        any_ev_truncated = any_ev_truncated or truncated
        evidence_projections.append(
            EntailmentEvidenceProjection(
                id=evidence.id,
                statement=ev_statement,
                source_excerpt=ev_excerpt,
                truncated=truncated,
            ),
        )

    truncated = stmt_truncated or rat_truncated or rq_truncated or any_ev_truncated
    return EntailmentCandidateProjection(
        candidate_id=item.candidate_id,
        statement=statement,
        rationale=rationale,
        evidence_refs=tuple(item.candidate.evidence_refs),
        research_question_text=rq_text,
        evidence=tuple(evidence_projections),
        truncated=truncated,
    )


def batch_entailment_candidates(
    projections: list[EntailmentCandidateProjection],
    *,
    max_candidates_per_batch: int = MAX_CANDIDATES_PER_ENTAILMENT_BATCH,
    max_chars_per_batch: int = MAX_CHARS_PER_ENTAILMENT_BATCH,
) -> list[list[EntailmentCandidateProjection]]:
    """Deterministic packing; every candidate appears in exactly one batch."""

    if max_candidates_per_batch < 1:
        raise FindingEntailmentError("max_candidates_per_batch must be >= 1")
    if max_chars_per_batch < 1:
        raise FindingEntailmentError("max_chars_per_batch must be >= 1")

    batches: list[list[EntailmentCandidateProjection]] = []
    current: list[EntailmentCandidateProjection] = []
    current_chars = 0
    for projection in projections:
        size = projection.char_count()
        would_exceed_count = len(current) >= max_candidates_per_batch
        would_exceed_chars = current and (current_chars + size > max_chars_per_batch)
        if current and (would_exceed_count or would_exceed_chars):
            batches.append(current)
            current = []
            current_chars = 0
        current.append(projection)
        current_chars += size
    if current:
        batches.append(current)
    return batches


def parse_entailment_payload(
    payload: dict[str, Any],
    *,
    submitted: list[EntailmentCandidateProjection],
) -> list[FindingEntailmentVerdict]:
    """Fail-closed structured parse for entailment validator output."""

    if not isinstance(payload, dict):
        raise FindingEntailmentError("Entailment payload must be a JSON object")

    raw_verdicts = payload.get("verdicts")
    if not isinstance(raw_verdicts, list):
        raise FindingEntailmentError("Entailment payload missing verdicts array")

    submitted_by_id = {item.candidate_id: item for item in submitted}
    seen: dict[str, FindingEntailmentVerdict] = {}

    for raw in raw_verdicts:
        if not isinstance(raw, dict):
            raise FindingEntailmentError("Entailment verdict must be an object")
        candidate_id = str(raw.get("candidate_id", "")).strip()
        if not candidate_id:
            raise FindingEntailmentError("Entailment verdict missing candidate_id")
        if candidate_id not in submitted_by_id:
            raise FindingEntailmentError(
                f"Unknown entailment candidate_id: {candidate_id}",
            )
        if candidate_id in seen:
            raise FindingEntailmentError(
                f"Duplicate entailment verdict for candidate_id: {candidate_id}",
            )

        status_raw = str(raw.get("status", "")).strip().upper()
        try:
            status = FindingEntailmentStatus(status_raw)
        except ValueError as exc:
            raise FindingEntailmentError(
                f"Malformed entailment status for {candidate_id}: {status_raw!r}",
            ) from exc

        supported_raw = raw.get("supported_evidence_ids", [])
        if not isinstance(supported_raw, list):
            raise FindingEntailmentError(
                f"supported_evidence_ids must be a list for {candidate_id}",
            )
        allowed_refs = set(submitted_by_id[candidate_id].evidence_refs)
        supported_ids: list[str] = []
        for ref in supported_raw:
            evidence_id = str(ref).strip()
            if not evidence_id:
                continue
            if evidence_id not in allowed_refs:
                raise FindingEntailmentError(
                    f"supported_evidence_ids includes non-referenced evidence "
                    f"{evidence_id} for {candidate_id}",
                )
            if evidence_id not in supported_ids:
                supported_ids.append(evidence_id)

        unsupported_raw = raw.get("unsupported_claim_parts", [])
        if unsupported_raw is None:
            unsupported_raw = []
        if not isinstance(unsupported_raw, list):
            raise FindingEntailmentError(
                f"unsupported_claim_parts must be a list for {candidate_id}",
            )
        unsupported_parts = tuple(
            str(part).strip() for part in unsupported_raw if str(part).strip()
        )
        rationale = str(raw.get("rationale", "")).strip()

        seen[candidate_id] = FindingEntailmentVerdict(
            candidate_id=candidate_id,
            status=status,
            supported_evidence_ids=tuple(supported_ids),
            unsupported_claim_parts=unsupported_parts,
            rationale=rationale,
        )

    missing = [item.candidate_id for item in submitted if item.candidate_id not in seen]
    if missing:
        raise FindingEntailmentError(
            f"Missing entailment verdicts for candidate_ids: {missing}",
        )

    ordered: list[FindingEntailmentVerdict] = []
    for item in submitted:
        verdict = seen[item.candidate_id]
        if item.truncated and verdict.status == FindingEntailmentStatus.SUPPORTED:
            # Truncated material must not silently certify support.
            ordered.append(
                FindingEntailmentVerdict(
                    candidate_id=verdict.candidate_id,
                    status=FindingEntailmentStatus.INSUFFICIENT_EVIDENCE,
                    supported_evidence_ids=verdict.supported_evidence_ids,
                    unsupported_claim_parts=verdict.unsupported_claim_parts
                    or ("input_truncated",),
                    rationale=(
                        "Input truncated; cannot certify SUPPORTED. "
                        + verdict.rationale
                    ).strip(),
                ),
            )
        else:
            ordered.append(verdict)
    return ordered


def assign_candidate_ids(
    candidates: list[FindingCandidate],
    *,
    start_index: int = 1,
) -> list[tuple[str, FindingCandidate]]:
    return [
        (f"fc-{start_index + offset:04d}", candidate)
        for offset, candidate in enumerate(candidates)
    ]


def resolve_research_question_text(
    candidate: FindingCandidate,
    *,
    questions_by_id: dict[str, ResearchQuestion],
) -> str | None:
    for ref in candidate.research_question_refs:
        question = questions_by_id.get(ref)
        if question is not None:
            return question.question
    return None


class FindingEntailmentValidator(Protocol):
    """Independent semantic gate; separate invocation from Finding generation."""

    def validate_batch(
        self,
        projections: list[EntailmentCandidateProjection],
    ) -> list[FindingEntailmentVerdict]:
        ...


class AcceptAllFindingEntailmentValidator:
    """Test/smoke validator: every candidate is SUPPORTED (no LLM call)."""

    def validate_batch(
        self,
        projections: list[EntailmentCandidateProjection],
    ) -> list[FindingEntailmentVerdict]:
        return [
            FindingEntailmentVerdict(
                candidate_id=item.candidate_id,
                status=FindingEntailmentStatus.SUPPORTED,
                supported_evidence_ids=tuple(item.evidence_refs),
                unsupported_claim_parts=(),
                rationale="accept_all",
            )
            for item in projections
        ]


class ScriptedFindingEntailmentValidator:
    """Offline test validator returning predetermined verdicts by candidate_id."""

    def __init__(
        self,
        verdicts_by_id: dict[str, FindingEntailmentVerdict] | None = None,
        *,
        status_by_id: dict[str, FindingEntailmentStatus] | None = None,
        default_status: FindingEntailmentStatus = FindingEntailmentStatus.SUPPORTED,
        fail_with: Exception | None = None,
        raw_payload_by_call: list[dict[str, Any]] | None = None,
    ) -> None:
        self._verdicts_by_id = dict(verdicts_by_id or {})
        self._status_by_id = dict(status_by_id or {})
        self._default_status = default_status
        self._fail_with = fail_with
        self._raw_payload_by_call = list(raw_payload_by_call or [])
        self.calls: list[list[EntailmentCandidateProjection]] = []

    def validate_batch(
        self,
        projections: list[EntailmentCandidateProjection],
    ) -> list[FindingEntailmentVerdict]:
        self.calls.append(list(projections))
        if self._fail_with is not None:
            raise self._fail_with
        if self._raw_payload_by_call:
            payload = self._raw_payload_by_call.pop(0)
            return parse_entailment_payload(payload, submitted=projections)

        verdicts: list[FindingEntailmentVerdict] = []
        for item in projections:
            if item.candidate_id in self._verdicts_by_id:
                verdicts.append(self._verdicts_by_id[item.candidate_id])
                continue
            status = self._status_by_id.get(item.candidate_id, self._default_status)
            verdicts.append(
                FindingEntailmentVerdict(
                    candidate_id=item.candidate_id,
                    status=status,
                    supported_evidence_ids=(
                        tuple(item.evidence_refs)
                        if status == FindingEntailmentStatus.SUPPORTED
                        else ()
                    ),
                    unsupported_claim_parts=(),
                    rationale=f"scripted:{status.value}",
                ),
            )
        return verdicts
