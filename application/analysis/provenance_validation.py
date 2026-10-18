from __future__ import annotations

from domain.evidence.evidence import Evidence
from domain.findings.finding import Finding
from domain.planning.research_design import ResearchDesign

from application.analysis.diagnostics import (
    REJECTION_CATEGORY_CROSS_DESIGN_REF,
    REJECTION_CATEGORY_CROSS_PROJECT_REF,
    REJECTION_CATEGORY_CROSS_RUN_REF,
    REJECTION_CATEGORY_INVALID_CONFIDENCE,
    REJECTION_CATEGORY_INVALID_EVIDENCE_REF,
    REJECTION_CATEGORY_MISSING_STATEMENT,
    REJECTION_CATEGORY_MISSING_SUPPORT,
)
from application.analysis.exceptions import InvalidAnalysisProvenanceError
from application.ports.analysis_ports import FindingCandidate, InsightCandidate


def validate_confidence(confidence: float | None) -> float | None:
    if confidence is None:
        return None
    if not 0.0 <= confidence <= 1.0:
        raise InvalidAnalysisProvenanceError(
            f"Confidence must be between 0 and 1, got {confidence}",
            category=REJECTION_CATEGORY_INVALID_CONFIDENCE,
        )
    return confidence


def validate_finding_candidate(
    candidate: FindingCandidate,
    *,
    evidence_by_id: dict[str, Evidence],
    project_id: str,
    workflow_run_id: str,
    research_design_id: str,
    design: ResearchDesign,
    eligible_information_need_ids: tuple[str, ...] | None = None,
    supported_aspects_by_information_need: dict[str, tuple[str, ...]] | None = None,
) -> FindingCandidate:
    if not candidate.statement.strip():
        raise InvalidAnalysisProvenanceError(
            "Finding statement must not be empty",
            category=REJECTION_CATEGORY_MISSING_STATEMENT,
        )
    if not candidate.evidence_refs:
        raise InvalidAnalysisProvenanceError(
            "Finding must reference at least one Evidence",
            category=REJECTION_CATEGORY_MISSING_SUPPORT,
        )

    allowed_questions = {question.id for question in design.research_questions}
    allowed_needs = {need.id for need in design.information_needs}

    for evidence_id in candidate.evidence_refs:
        evidence = evidence_by_id.get(evidence_id)
        if evidence is None:
            raise InvalidAnalysisProvenanceError(
                f"Unknown evidence reference: {evidence_id}",
                category=REJECTION_CATEGORY_INVALID_EVIDENCE_REF,
            )
        if evidence.project_id != project_id:
            raise InvalidAnalysisProvenanceError(
                f"Evidence {evidence_id} belongs to a different project",
                category=REJECTION_CATEGORY_CROSS_PROJECT_REF,
            )
        if evidence.workflow_run_id != workflow_run_id:
            raise InvalidAnalysisProvenanceError(
                f"Evidence {evidence_id} belongs to a different workflow run",
                category=REJECTION_CATEGORY_CROSS_RUN_REF,
            )
        if evidence.research_design_id != research_design_id:
            raise InvalidAnalysisProvenanceError(
                f"Evidence {evidence_id} belongs to a different research design",
                category=REJECTION_CATEGORY_CROSS_DESIGN_REF,
            )

    cited_evidence = [evidence_by_id[ref] for ref in candidate.evidence_refs]
    cited_need_refs = {
        ref for evidence in cited_evidence for ref in evidence.information_need_refs
        if ref in allowed_needs
    }
    if eligible_information_need_ids is not None:
        eligible = set(eligible_information_need_ids)
        cited_need_refs &= eligible
        requested = set(candidate.information_need_refs)
        if requested and not requested <= cited_need_refs:
            raise InvalidAnalysisProvenanceError(
                "Finding references an ineligible or unsupported InformationNeed",
                category=REJECTION_CATEGORY_INVALID_EVIDENCE_REF,
            )
    need_refs = tuple(sorted(set(candidate.information_need_refs) or cited_need_refs))
    if eligible_information_need_ids is not None and not need_refs:
        raise InvalidAnalysisProvenanceError(
            "Finding has no eligible InformationNeed support",
            category=REJECTION_CATEGORY_INVALID_EVIDENCE_REF,
        )
    need_to_rq = {need.id: need.research_question_id for need in design.information_needs}
    question_refs = (
        tuple(sorted({need_to_rq[ref] for ref in need_refs}))
        if need_refs else tuple(
            ref for ref in candidate.research_question_refs if ref in allowed_questions
        )
    )
    if need_refs and not set(question_refs) <= allowed_questions:
        raise InvalidAnalysisProvenanceError(
            "Finding InformationNeed maps outside the current Design",
            category=REJECTION_CATEGORY_CROSS_DESIGN_REF,
        )

    confidence = validate_confidence(candidate.confidence)
    metadata = dict(candidate.metadata or {})
    claimed_aspects = metadata.get("required_aspect_refs", [])
    if claimed_aspects is None:
        claimed_aspects = []
    if not isinstance(claimed_aspects, (list, tuple)):
        raise InvalidAnalysisProvenanceError(
            "Finding required_aspect_refs must be an array",
            category=REJECTION_CATEGORY_INVALID_EVIDENCE_REF,
        )
    if supported_aspects_by_information_need is not None:
        allowed_aspects = {
            aspect for need_id in need_refs
            for aspect in supported_aspects_by_information_need.get(need_id, ())
        }
        if not set(str(item) for item in claimed_aspects) <= allowed_aspects:
            raise InvalidAnalysisProvenanceError(
                "Finding claims an unsupported required aspect",
                category=REJECTION_CATEGORY_INVALID_EVIDENCE_REF,
            )
        metadata["required_aspect_refs"] = sorted(
            set(str(item) for item in claimed_aspects)
        )
        metadata["analysis_scope_information_need_ids"] = list(need_refs)
    if candidate.finding_type == "contradiction" or metadata.get("conflicting_evidence"):
        metadata.setdefault("conflict_signal", True)

    return FindingCandidate(
        statement=candidate.statement.strip(),
        rationale=candidate.rationale.strip(),
        evidence_refs=tuple(sorted(set(candidate.evidence_refs))),
        research_question_refs=question_refs,
        information_need_refs=need_refs,
        finding_type=candidate.finding_type,
        confidence=confidence,
        metadata=metadata,
    )


def validate_insight_candidate(
    candidate: InsightCandidate,
    *,
    findings_by_id: dict[str, Finding],
    project_id: str,
    workflow_run_id: str,
    research_design_id: str,
    design: ResearchDesign,
    eligible_information_need_ids: tuple[str, ...] | None = None,
) -> InsightCandidate:
    if not candidate.statement.strip():
        raise InvalidAnalysisProvenanceError("Insight statement must not be empty")
    if not candidate.finding_refs:
        raise InvalidAnalysisProvenanceError("Insight must reference at least one Finding")

    allowed_questions = {question.id for question in design.research_questions}

    for finding_id in candidate.finding_refs:
        finding = findings_by_id.get(finding_id)
        if finding is None:
            raise InvalidAnalysisProvenanceError(
                f"Unknown finding reference: {finding_id}",
            )
        if finding.project_id != project_id:
            raise InvalidAnalysisProvenanceError(
                f"Finding {finding_id} belongs to a different project",
            )
        if finding.workflow_run_id != workflow_run_id:
            raise InvalidAnalysisProvenanceError(
                f"Finding {finding_id} belongs to a different workflow run",
            )
        if finding.research_design_id != research_design_id:
            raise InvalidAnalysisProvenanceError(
                f"Finding {finding_id} belongs to a different research design",
            )

    question_refs = tuple(
        ref for ref in candidate.research_question_refs if ref in allowed_questions
    )
    derived_question_refs = tuple(sorted({
        ref
        for finding_id in candidate.finding_refs
        for ref in findings_by_id[finding_id].research_question_refs
        if ref in allowed_questions
    }))
    if candidate.research_question_refs and not set(question_refs) <= set(derived_question_refs):
        raise InvalidAnalysisProvenanceError(
            "Insight references unsupported ResearchQuestion scope",
        )
    question_refs = derived_question_refs
    if eligible_information_need_ids is not None:
        eligible = set(eligible_information_need_ids)
        if any(
            not set(findings_by_id[ref].information_need_refs) <= eligible
            for ref in candidate.finding_refs
        ):
            raise InvalidAnalysisProvenanceError(
                "Insight references a Finding outside eligible analysis scope",
            )
    confidence = validate_confidence(candidate.confidence)

    return InsightCandidate(
        statement=candidate.statement.strip(),
        implication=candidate.implication.strip(),
        finding_refs=tuple(sorted(set(candidate.finding_refs))),
        research_question_refs=question_refs,
        confidence=confidence,
        metadata=dict(candidate.metadata or {}),
    )
